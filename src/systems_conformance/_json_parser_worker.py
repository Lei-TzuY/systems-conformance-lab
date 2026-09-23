from __future__ import annotations

import argparse
import json
import math
import platform
import sys
from collections.abc import Sequence

DEFAULT_MAX_JSON_DOCUMENT_BYTES = 64 * 1024
MAX_CONFIGURED_JSON_DOCUMENT_BYTES = 1024 * 1024


def _bounded_document_bytes(value: str) -> int:
    parsed = int(value)
    if parsed < 0 or parsed > MAX_CONFIGURED_JSON_DOCUMENT_BYTES:
        raise argparse.ArgumentTypeError(
            "max document bytes must be between 0 and "
            f"{MAX_CONFIGURED_JSON_DOCUMENT_BYTES}"
        )
    return parsed


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--python-implementation", required=True)
    parser.add_argument("--python-version", required=True)
    parser.add_argument(
        "--max-document-bytes",
        required=True,
        type=_bounded_document_bytes,
        default=DEFAULT_MAX_JSON_DOCUMENT_BYTES,
    )
    return parser.parse_args(argv)


def _runtime_identity_matches(args: argparse.Namespace) -> bool:
    return (
        args.python_implementation == sys.implementation.name
        and args.python_version == platform.python_version()
    )


def _emit(value: dict[str, object]) -> None:
    payload = json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    sys.stdout.buffer.write((payload + "\n").encode("ascii"))


def _has_non_finite(value: object) -> bool:
    if isinstance(value, float):
        return not math.isfinite(value)
    if isinstance(value, list):
        return any(_has_non_finite(item) for item in value)
    if isinstance(value, dict):
        return any(_has_non_finite(item) for item in value.values())
    return False


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    if not _runtime_identity_matches(args):
        sys.stderr.write("json_parser_runtime_identity_mismatch\n")
        return 3

    raw = sys.stdin.buffer.read(args.max_document_bytes + 1)
    if len(raw) > args.max_document_bytes:
        _emit({"error": "input_too_large", "ok": False})
        return 0

    try:
        text = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        _emit({"error": "utf8_decode_error", "ok": False})
        return 0

    try:
        value = json.loads(text)
    except (json.JSONDecodeError, RecursionError):
        _emit({"error": "json_parse_error", "ok": False})
        return 0

    try:
        if _has_non_finite(value):
            _emit({"error": "non_finite_number", "ok": False})
            return 0
    except RecursionError:
        _emit({"error": "json_result_error", "ok": False})
        return 0

    try:
        _emit({"ok": True, "value": value})
    except (RecursionError, ValueError):
        _emit({"error": "json_result_error", "ok": False})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
