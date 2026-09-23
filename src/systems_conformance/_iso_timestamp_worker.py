from __future__ import annotations

import argparse
import json
import platform
import re
import sys
from collections.abc import Sequence
from datetime import datetime, timezone

_EXPLICIT_TIMEZONE = re.compile(
    r"(?:Z|[+-]\d{2}(?::?\d{2})?(?::?\d{2}(?:[.,]\d+)?)?)$"
)
_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


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


def _has_explicit_timezone(text: str) -> bool:
    if len(text) <= 10:
        return False
    return _EXPLICIT_TIMEZONE.search(text[10:]) is not None


def _epoch_milliseconds(value: datetime) -> int:
    utc_value = value.astimezone(timezone.utc)
    delta = utc_value - _EPOCH
    return (
        delta.days * 86_400_000
        + delta.seconds * 1000
        + delta.microseconds // 1000
    )


def _utc_iso_milliseconds(value: datetime) -> str:
    utc_value = value.astimezone(timezone.utc)
    milliseconds = utc_value.microsecond // 1000
    return (
        f"{utc_value.year:04d}-{utc_value.month:02d}-{utc_value.day:02d}"
        f"T{utc_value.hour:02d}:{utc_value.minute:02d}:{utc_value.second:02d}"
        f".{milliseconds:03d}Z"
    )


def _parse_timestamp(raw: bytes) -> dict[str, object]:
    try:
        text = raw.decode("ascii", errors="strict")
    except UnicodeDecodeError:
        return {"error": "ascii_decode_error", "ok": False}

    try:
        value = datetime.fromisoformat(text)
    except ValueError:
        return {"error": "iso_timestamp_parse_error", "ok": False}

    if not _has_explicit_timezone(text) or value.tzinfo is None:
        return {"error": "timezone_required", "ok": False}

    return {
        "epoch_milliseconds": _epoch_milliseconds(value),
        "iso_utc": _utc_iso_milliseconds(value),
        "ok": True,
    }


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    if not _runtime_identity_matches(args):
        sys.stderr.write("iso_timestamp_runtime_identity_mismatch\n")
        return 3

    output = _parse_timestamp(sys.stdin.buffer.read())
    sys.stdout.buffer.write(_encode_result(output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
