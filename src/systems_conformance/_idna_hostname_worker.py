from __future__ import annotations

import argparse
import json
import platform
import sys
import unicodedata
from collections.abc import Sequence


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--python-implementation", required=True)
    parser.add_argument("--python-version", required=True)
    parser.add_argument("--idna-unicode-version", required=True)
    return parser.parse_args(argv)


def _runtime_identity_matches(args: argparse.Namespace) -> bool:
    return (
        args.python_implementation == sys.implementation.name
        and args.python_version == platform.python_version()
        and args.idna_unicode_version == unicodedata.ucd_3_2_0.unidata_version
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


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    if not _runtime_identity_matches(args):
        sys.stderr.write("idna_hostname_runtime_identity_mismatch\n")
        return 3

    raw = sys.stdin.buffer.read()
    try:
        hostname = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        output = _encode_result(
            {
                "error": "unicode_decode_error",
                "ok": False,
            }
        )
    else:
        if not hostname:
            output = _encode_result(
                {
                    "error": "idna_error",
                    "ok": False,
                }
            )
        else:
            try:
                ascii_hostname = hostname.encode("idna").decode("ascii")
            except UnicodeError:
                output = _encode_result(
                    {
                        "error": "idna_error",
                        "ok": False,
                    }
                )
            else:
                output = _encode_result(
                    {
                        "ascii": ascii_hostname,
                        "ok": True,
                    }
                )

    sys.stdout.buffer.write(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
