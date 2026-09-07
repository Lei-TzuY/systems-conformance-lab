from __future__ import annotations

import argparse
import io
import sys
from collections.abc import Sequence
from typing import Any

from . import _sqlite_worker as worker


def _validate_json_depth(raw: bytes, *, max_json_depth: int) -> None:
    """Reject JSON whose structural nesting exceeds the configured ceiling."""

    depth = 0
    in_string = False
    escaped = False
    for byte in raw:
        if in_string:
            if escaped:
                escaped = False
            elif byte == ord("\\"):
                escaped = True
            elif byte == ord('"'):
                in_string = False
            continue

        if byte == ord('"'):
            in_string = True
        elif byte in (ord("{"), ord("[")):
            depth += 1
            if depth > max_json_depth:
                raise worker.ProtocolError(
                    f"request exceeds max_json_depth: {max_json_depth}"
                )
        elif byte in (ord("}"), ord("]")):
            depth -= 1


def _parse_resource_args(argv: Sequence[str] | None) -> tuple[int, int, list[str]]:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--max-json-depth", required=True, type=worker._positive_int)
    parser.add_argument("--max-result-value-bytes", required=True, type=worker._positive_int)
    args, remaining = parser.parse_known_args(argv)
    return args.max_json_depth, args.max_result_value_bytes, remaining


def _bounded_normalize(value: Any, *, max_result_value_bytes: int) -> Any:
    if isinstance(value, bytes):
        size = len(value)
    elif isinstance(value, str):
        size = len(value.encode("utf-8"))
    else:
        return worker._normalize(value)
    if size > max_result_value_bytes:
        raise ValueError(f"result value exceeds max_result_value_bytes: {max_result_value_bytes}")
    return worker._normalize(value)


def main(argv: Sequence[str] | None = None) -> int:
    max_json_depth, max_result_value_bytes, worker_argv = _parse_resource_args(argv)
    raw = sys.stdin.buffer.read()
    try:
        _validate_json_depth(raw, max_json_depth=max_json_depth)
    except worker.ProtocolError as exc:
        sys.stderr.write(f"protocol_error: {exc}\n")
        return 2

    replay_stdin = io.TextIOWrapper(io.BytesIO(raw), encoding="utf-8")
    original_stdin = sys.stdin
    original_normalize = worker._normalize
    sys.stdin = replay_stdin
    worker._normalize = lambda value: _bounded_normalize(
        value, max_result_value_bytes=max_result_value_bytes
    )
    try:
        return worker.main(worker_argv)
    finally:
        worker._normalize = original_normalize
        sys.stdin = original_stdin


if __name__ == "__main__":
    raise SystemExit(main())
