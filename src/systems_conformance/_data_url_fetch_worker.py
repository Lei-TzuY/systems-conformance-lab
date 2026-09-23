from __future__ import annotations

import argparse
import binascii
import json
import platform
import sys
from collections.abc import Sequence
from urllib.error import URLError
from urllib.request import urlopen

DEFAULT_MAX_DATA_URL_BYTES = 64 * 1024
MAX_CONFIGURED_DATA_URL_BYTES = 1024 * 1024


def _positive_bounded_integer(value: str) -> int:
    parsed = int(value)
    if parsed <= 0 or parsed > MAX_CONFIGURED_DATA_URL_BYTES:
        raise argparse.ArgumentTypeError(
            "max data URL bytes must be between 1 and "
            f"{MAX_CONFIGURED_DATA_URL_BYTES}"
        )
    return parsed


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument(
        "--max-data-url-bytes",
        type=_positive_bounded_integer,
        default=DEFAULT_MAX_DATA_URL_BYTES,
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


def _read_bounded_input(max_bytes: int) -> bytes | None:
    raw = sys.stdin.buffer.read(max_bytes + 1)
    if len(raw) > max_bytes:
        return None
    return raw


def _fetch_data_url(raw: bytes, max_data_url_bytes: int) -> dict[str, object]:
    if len(raw) > max_data_url_bytes:
        return {"error": "data_url_too_large", "ok": False}

    try:
        text = raw.decode("ascii", errors="strict")
    except UnicodeDecodeError:
        return {"error": "ascii_decode_error", "ok": False}

    if text[:5].lower() != "data:":
        return {"error": "unsupported_scheme", "ok": False}

    try:
        with urlopen(text) as response:
            body = response.read()
            content_type = response.headers.get("Content-Type")
    except (ValueError, binascii.Error, URLError, OSError):
        return {"error": "data_url_error", "ok": False}

    if len(body) > max_data_url_bytes:
        return {"error": "decoded_body_too_large", "ok": False}
    if not isinstance(content_type, str):
        return {"error": "data_url_error", "ok": False}

    return {
        "body_hex": body.hex(),
        "content_type": content_type,
        "ok": True,
    }


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    if not _runtime_identity_matches(args):
        sys.stderr.write("data_url_runtime_identity_mismatch\n")
        return 3

    raw = _read_bounded_input(args.max_data_url_bytes)
    output = (
        {"error": "data_url_too_large", "ok": False}
        if raw is None
        else _fetch_data_url(raw, args.max_data_url_bytes)
    )
    sys.stdout.buffer.write(_encode_result(output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
