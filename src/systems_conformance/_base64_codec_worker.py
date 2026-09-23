from __future__ import annotations

import argparse
import base64
import binascii
import json
import platform
import sys
from collections.abc import Sequence


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--mode", choices=("encode", "decode"), required=True)
    parser.add_argument("--alphabet", choices=("base64", "base64url"), required=True)
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


def _encode(raw: bytes, alphabet: str) -> dict[str, object]:
    encoded = base64.b64encode(raw) if alphabet == "base64" else base64.urlsafe_b64encode(raw)
    return {"encoded": encoded.decode("ascii"), "ok": True}


def _decode(raw: bytes, alphabet: str) -> dict[str, object]:
    try:
        text = raw.decode("ascii", errors="strict")
    except UnicodeDecodeError:
        return {"error": "ascii_decode_error", "ok": False}

    try:
        decoded = (
            base64.b64decode(text, validate=False)
            if alphabet == "base64"
            else base64.urlsafe_b64decode(text)
        )
    except (binascii.Error, ValueError):
        return {"error": "base64_decode_error", "ok": False}

    return {"hex": decoded.hex(), "ok": True}


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    if not _runtime_identity_matches(args):
        sys.stderr.write("base64_codec_runtime_identity_mismatch\n")
        return 3

    raw = sys.stdin.buffer.read()
    output = _encode(raw, args.alphabet) if args.mode == "encode" else _decode(raw, args.alphabet)
    sys.stdout.buffer.write(_encode_result(output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
