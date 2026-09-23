from __future__ import annotations

import argparse
import json
import platform
import socket
import sys
import threading
from collections.abc import Sequence
from http.client import IncompleteRead
from urllib.error import URLError
from urllib.request import urlopen

DEFAULT_MAX_TRANSFER_BODY_BYTES = 64 * 1024
DEFAULT_MAX_OBSERVED_BODY_BYTES = 64 * 1024
MAX_CONFIGURED_BODY_BYTES = 1024 * 1024

_IDENTITY = 0
_GZIP = 1


def _positive_bounded_integer(value: str) -> int:
    parsed = int(value)
    if parsed <= 0 or parsed > MAX_CONFIGURED_BODY_BYTES:
        raise argparse.ArgumentTypeError(
            f"body byte budgets must be between 1 and {MAX_CONFIGURED_BODY_BYTES}"
        )
    return parsed


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument(
        "--max-transfer-body-bytes",
        type=_positive_bounded_integer,
        default=DEFAULT_MAX_TRANSFER_BODY_BYTES,
    )
    parser.add_argument(
        "--max-observed-body-bytes",
        type=_positive_bounded_integer,
        default=DEFAULT_MAX_OBSERVED_BODY_BYTES,
    )
    parser.add_argument("--python-implementation", required=True)
    parser.add_argument("--python-version", required=True)
    return parser.parse_args(argv)


def _runtime_identity_matches(args: argparse.Namespace) -> bool:
    return (
        args.python_implementation == sys.implementation.name
        and args.python_version == platform.python_version()
    )


def _encode_result(value: dict[str, object]) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        + b"\n"
    )


def _read_bounded_case(max_transfer_body_bytes: int) -> bytes | None:
    raw = sys.stdin.buffer.read(max_transfer_body_bytes + 2)
    if len(raw) > max_transfer_body_bytes + 1:
        return None
    return raw


def _parse_case(raw: bytes) -> tuple[str | None, bytes] | None:
    if not raw:
        return None
    mode = raw[0]
    if mode == _IDENTITY:
        content_encoding = None
    elif mode == _GZIP:
        content_encoding = "gzip"
    else:
        return None
    return content_encoding, raw[1:]


def _serve_once(
    listener: socket.socket,
    *,
    transfer_body: bytes,
    content_encoding: str | None,
    errors: list[str],
) -> None:
    try:
        connection, _ = listener.accept()
        with connection:
            connection.settimeout(5.0)
            request = bytearray()
            while b"\r\n\r\n" not in request:
                chunk = connection.recv(4096)
                if not chunk:
                    break
                request.extend(chunk)
                if len(request) > 64 * 1024:
                    raise RuntimeError("request headers too large")

            headers = [
                b"HTTP/1.1 200 OK",
                b"Content-Type: application/octet-stream",
                b"Transfer-Encoding: chunked",
            ]
            if content_encoding is not None:
                headers.append(b"Content-Encoding: gzip")
            headers.append(b"Connection: close")
            connection.sendall(b"\r\n".join(headers) + b"\r\n\r\n" + transfer_body)
    except (OSError, RuntimeError):
        errors.append("loopback_server_error")
    finally:
        listener.close()


def _fetch_loopback(
    *,
    transfer_body: bytes,
    content_encoding: str | None,
    max_observed_body_bytes: int,
) -> dict[str, object]:
    errors: list[str] = []
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.settimeout(5.0)
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    port = listener.getsockname()[1]

    thread = threading.Thread(
        target=_serve_once,
        kwargs={
            "listener": listener,
            "transfer_body": transfer_body,
            "content_encoding": content_encoding,
            "errors": errors,
        },
        daemon=True,
    )
    thread.start()

    try:
        with urlopen(f"http://127.0.0.1:{port}/", timeout=5.0) as response:
            transfer_encoding = response.headers.get("Transfer-Encoding")
            observed_content_encoding = response.headers.get("Content-Encoding")
            content_length = response.headers.get("Content-Length")
            try:
                observed = response.read(max_observed_body_bytes + 1)
            except IncompleteRead:
                return {"error": "body_decode_error", "ok": False}
    except (OSError, URLError, ValueError):
        return {"error": "http_fetch_error", "ok": False}
    finally:
        thread.join(timeout=5.0)

    if thread.is_alive() or errors:
        return {"error": "loopback_server_error", "ok": False}
    if len(observed) > max_observed_body_bytes:
        return {"error": "observed_body_too_large", "ok": False}

    return {
        "body_hex": observed.hex(),
        "content_encoding": observed_content_encoding,
        "content_length": content_length,
        "ok": True,
        "transfer_encoding": transfer_encoding,
    }


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    if not _runtime_identity_matches(args):
        sys.stderr.write(
            "http_chunked_content_encoding_runtime_identity_mismatch\n"
        )
        return 3

    raw = _read_bounded_case(args.max_transfer_body_bytes)
    if raw is None:
        output = {"error": "transfer_body_too_large", "ok": False}
    else:
        parsed = _parse_case(raw)
        if parsed is None:
            output = {"error": "protocol_error", "ok": False}
        else:
            content_encoding, transfer_body = parsed
            output = _fetch_loopback(
                transfer_body=transfer_body,
                content_encoding=content_encoding,
                max_observed_body_bytes=args.max_observed_body_bytes,
            )

    sys.stdout.buffer.write(_encode_result(output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
