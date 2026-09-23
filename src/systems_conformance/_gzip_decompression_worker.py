from __future__ import annotations

import argparse
import gzip
import io
import json
import platform
import sys
import zlib
from collections.abc import Sequence

DEFAULT_MAX_DECOMPRESSED_BYTES = 64 * 1024
MAX_CONFIGURED_DECOMPRESSED_BYTES = 16 * 1024 * 1024


def _positive_bounded_integer(value: str) -> int:
    parsed = int(value)
    if parsed <= 0 or parsed > MAX_CONFIGURED_DECOMPRESSED_BYTES:
        raise argparse.ArgumentTypeError(
            "max decompressed bytes must be between 1 and "
            f"{MAX_CONFIGURED_DECOMPRESSED_BYTES}"
        )
    return parsed


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument(
        "--max-decompressed-bytes",
        type=_positive_bounded_integer,
        default=DEFAULT_MAX_DECOMPRESSED_BYTES,
    )
    parser.add_argument("--python-implementation", required=True)
    parser.add_argument("--python-version", required=True)
    parser.add_argument("--zlib-version", required=True)
    return parser.parse_args(argv)


def _runtime_identity_matches(args: argparse.Namespace) -> bool:
    return (
        args.python_implementation == sys.implementation.name
        and args.python_version == platform.python_version()
        and args.zlib_version == zlib.ZLIB_RUNTIME_VERSION
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


def _decompress(raw: bytes, max_decompressed_bytes: int) -> dict[str, object]:
    try:
        with gzip.GzipFile(fileobj=io.BytesIO(raw), mode="rb") as handle:
            decoded = handle.read(max_decompressed_bytes + 1)
    except (gzip.BadGzipFile, EOFError, OSError, zlib.error):
        return {"error": "gzip_decode_error", "ok": False}

    if len(decoded) > max_decompressed_bytes:
        return {"error": "decompressed_output_too_large", "ok": False}

    return {"hex": decoded.hex(), "ok": True}


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    if not _runtime_identity_matches(args):
        sys.stderr.write("gzip_runtime_identity_mismatch\n")
        return 3

    output = _decompress(
        sys.stdin.buffer.read(),
        args.max_decompressed_bytes,
    )
    sys.stdout.buffer.write(_encode_result(output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
