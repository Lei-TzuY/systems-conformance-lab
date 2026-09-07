from __future__ import annotations

import argparse
import io
import sys
from collections.abc import Sequence

from . import _sqlite_transaction_worker as worker


def _validate_json_depth(raw: bytes, *, max_json_depth: int) -> None:
    """Reject JSON whose structural nesting exceeds the configured ceiling.

    This is a preflight over raw bytes so deeply nested malformed input is
    rejected before ``json.loads`` can consume Python recursion budget. JSON
    delimiters inside strings are ignored, including escaped quotes.
    """

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


def _parse_depth_arg(
    argv: Sequence[str] | None,
) -> tuple[int, list[str]]:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--max-json-depth", required=True, type=worker._positive_int)
    args, remaining = parser.parse_known_args(argv)
    return args.max_json_depth, remaining


def main(argv: Sequence[str] | None = None) -> int:
    max_json_depth, worker_argv = _parse_depth_arg(argv)
    raw = sys.stdin.buffer.read()
    try:
        _validate_json_depth(raw, max_json_depth=max_json_depth)
    except worker.ProtocolError as exc:
        sys.stderr.write(f"protocol_error: {exc}\n")
        return 2

    replay_stdin = io.TextIOWrapper(io.BytesIO(raw), encoding="utf-8")
    original_stdin = sys.stdin
    sys.stdin = replay_stdin
    try:
        return worker.main(worker_argv)
    finally:
        sys.stdin = original_stdin


if __name__ == "__main__":
    raise SystemExit(main())
