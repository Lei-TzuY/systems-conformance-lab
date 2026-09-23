from __future__ import annotations

import argparse
import json
import sys
import unicodedata
from collections.abc import Sequence


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--form", choices=("NFC", "NFD", "NFKC", "NFKD"), required=True)
    return parser.parse_args(argv)


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
        output = _encode_result(
            {
                "ok": True,
                "text": unicodedata.normalize(args.form, text),
            }
        )

    sys.stdout.buffer.write(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
