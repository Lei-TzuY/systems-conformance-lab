from __future__ import annotations

import argparse
import json
import platform
import sys
from collections.abc import Sequence
from urllib.parse import parse_qsl, urlencode


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--mode", choices=("encode", "decode"), required=True)
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


def _read_u32(raw: bytes, offset: int) -> tuple[int, int]:
    end = offset + 4
    if end > len(raw):
        raise ValueError("request framing is truncated")
    return int.from_bytes(raw[offset:end], "big"), end


def _decode_pairs_request(raw: bytes) -> list[tuple[str, str]]:
    pair_count, offset = _read_u32(raw, 0)
    if pair_count > (len(raw) - offset) // 8:
        raise ValueError("pair count exceeds request framing")

    pairs: list[tuple[str, str]] = []
    for _ in range(pair_count):
        key_length, offset = _read_u32(raw, offset)
        key_end = offset + key_length
        if key_end > len(raw):
            raise ValueError("key length exceeds request framing")
        key_raw = raw[offset:key_end]
        offset = key_end

        value_length, offset = _read_u32(raw, offset)
        value_end = offset + value_length
        if value_end > len(raw):
            raise ValueError("value length exceeds request framing")
        value_raw = raw[offset:value_end]
        offset = value_end

        pairs.append(
            (
                key_raw.decode("utf-8", errors="strict"),
                value_raw.decode("utf-8", errors="strict"),
            )
        )

    if offset != len(raw):
        raise ValueError("request contains trailing bytes")
    return pairs


def _encode_form(raw: bytes) -> dict[str, object]:
    try:
        pairs = _decode_pairs_request(raw)
    except UnicodeDecodeError:
        return {
            "error": "unicode_decode_error",
            "ok": False,
        }
    except ValueError:
        return {
            "error": "request_error",
            "ok": False,
        }

    return {
        "form": urlencode(
            pairs,
            doseq=False,
            encoding="utf-8",
            errors="strict",
        ),
        "ok": True,
    }


def _decode_form(raw: bytes) -> dict[str, object]:
    try:
        text = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        return {
            "error": "unicode_decode_error",
            "ok": False,
        }

    try:
        pairs = parse_qsl(
            text,
            keep_blank_values=True,
            strict_parsing=False,
            encoding="utf-8",
            errors="strict",
            separator="&",
        )
    except UnicodeDecodeError:
        return {
            "error": "form_decode_error",
            "ok": False,
        }

    return {
        "ok": True,
        "pairs": pairs,
    }


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    if not _runtime_identity_matches(args):
        sys.stderr.write("form_urlencoded_runtime_identity_mismatch\n")
        return 3

    raw = sys.stdin.buffer.read()
    output = _encode_form(raw) if args.mode == "encode" else _decode_form(raw)
    sys.stdout.buffer.write(_encode_result(output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
