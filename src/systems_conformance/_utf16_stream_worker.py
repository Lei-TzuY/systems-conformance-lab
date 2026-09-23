from __future__ import annotations

import argparse
import codecs
import json
import sys
from collections.abc import Sequence


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("value must be positive")
    return parsed


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--byte-order", choices=("le", "be"), required=True)
    parser.add_argument("--mode", choices=("oneshot", "incremental"), required=True)
    parser.add_argument("--errors", choices=("strict", "replace"), required=True)
    parser.add_argument("--chunk-size", type=_positive_int, required=True)
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


def _decode_incremental(
    raw: bytes,
    *,
    codec_name: str,
    errors: str,
    chunk_size: int,
) -> str:
    decoder_type = codecs.getincrementaldecoder(codec_name)
    decoder = decoder_type(errors=errors)
    pieces: list[str] = []
    for start in range(0, len(raw), chunk_size):
        pieces.append(decoder.decode(raw[start : start + chunk_size], final=False))
    pieces.append(decoder.decode(b"", final=True))
    return "".join(pieces)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    codec_name = "utf-16-le" if args.byte_order == "le" else "utf-16-be"
    raw = sys.stdin.buffer.read()

    try:
        if args.mode == "oneshot":
            text = raw.decode(codec_name, errors=args.errors)
        else:
            text = _decode_incremental(
                raw,
                codec_name=codec_name,
                errors=args.errors,
                chunk_size=args.chunk_size,
            )
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
                "text": text,
            }
        )

    sys.stdout.buffer.write(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
