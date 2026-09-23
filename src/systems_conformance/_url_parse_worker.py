from __future__ import annotations

import argparse
import json
import platform
import sys
from collections.abc import Sequence
from urllib.parse import urlsplit


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(add_help=False)
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


def _parse_http_url(text: str) -> dict[str, object]:
    parsed = urlsplit(text)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("unsupported URL scheme")
    hostname = parsed.hostname
    if not hostname:
        raise ValueError("URL hostname is required")
    port = parsed.port
    return {
        "fragment": parsed.fragment,
        "hostname": hostname,
        "ok": True,
        "password": parsed.password or "",
        "path": parsed.path,
        "port": "" if port is None else str(port),
        "query": parsed.query,
        "scheme": parsed.scheme,
        "username": parsed.username or "",
    }


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    if not _runtime_identity_matches(args):
        sys.stderr.write("url_parser_runtime_identity_mismatch\n")
        return 3

    raw = sys.stdin.buffer.read()
    try:
        text = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        output = _encode_result(
            {
                "error": "unicode_decode_error",
                "ok": False,
            }
        )
    else:
        try:
            value = _parse_http_url(text)
        except (UnicodeError, ValueError):
            output = _encode_result(
                {
                    "error": "url_parse_error",
                    "ok": False,
                }
            )
        else:
            output = _encode_result(value)

    sys.stdout.buffer.write(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
