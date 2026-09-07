from __future__ import annotations

import argparse
import io
import json
import sys
from collections.abc import Sequence
from typing import Any

from . import _sqlite_transaction_worker as worker

_ORIGINAL_DECODE_STATEMENT = worker._decode_statement
_ORIGINAL_EXECUTE_STATEMENT = worker._execute_statement


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


def _parse_resource_args(
    argv: Sequence[str] | None,
) -> tuple[int, int, int, int, int, int, int, list[str]]:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--max-json-depth", required=True, type=worker._positive_int)
    parser.add_argument("--max-params", required=True, type=worker._positive_int)
    parser.add_argument("--max-result-rows", required=True, type=worker._positive_int)
    parser.add_argument("--max-result-columns", required=True, type=worker._positive_int)
    parser.add_argument(
        "--max-result-value-bytes", required=True, type=worker._positive_int
    )
    parser.add_argument("--max-result-bytes", required=True, type=worker._positive_int)
    parser.add_argument(
        "--max-transcript-result-bytes", required=True, type=worker._positive_int
    )
    args, remaining = parser.parse_known_args(argv)
    return (
        args.max_json_depth,
        args.max_params,
        args.max_result_rows,
        args.max_result_columns,
        args.max_result_value_bytes,
        args.max_result_bytes,
        args.max_transcript_result_bytes,
        remaining,
    )


def _bounded_decode_statement(
    value: Any,
    *,
    field: str,
    max_sql_bytes: int,
    max_params: int,
) -> Any:
    statement = _ORIGINAL_DECODE_STATEMENT(
        value,
        field=field,
        max_sql_bytes=max_sql_bytes,
    )
    if len(statement.params) > max_params:
        raise worker.ProtocolError(f"{field} params exceeds max_params: {max_params}")
    return statement


def _bounded_normalize(value: Any, *, max_result_value_bytes: int) -> Any:
    if isinstance(value, bytes):
        size = len(value)
    elif isinstance(value, str):
        size = len(value.encode("utf-8"))
    else:
        return worker._normalize(value)
    if size > max_result_value_bytes:
        raise ValueError(
            f"result value exceeds max_result_value_bytes: {max_result_value_bytes}"
        )
    return worker._normalize(value)


def _serialized_json_size(value: Any) -> int:
    return len(
        json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    )


def _bounded_execute_statement(
    connection: Any,
    statement: Any,
    *,
    max_result_rows: int,
    max_result_columns: int,
    max_result_value_bytes: int,
    max_result_bytes: int,
) -> dict[str, Any]:
    cursor = connection.execute(statement.sql, statement.params)
    column_count = 0 if cursor.description is None else len(cursor.description)
    if column_count > max_result_columns:
        raise ValueError(f"result exceeds max_result_columns: {max_result_columns}")
    columns = [] if cursor.description is None else [item[0] for item in cursor.description]
    rows: list[list[Any]] = []
    used_bytes = 2
    if used_bytes > max_result_bytes:
        raise ValueError(f"result exceeds max_result_bytes: {max_result_bytes}")
    for row in cursor:
        if len(rows) >= max_result_rows:
            raise ValueError(f"result exceeds max_result_rows: {max_result_rows}")
        normalized_row: list[Any] = []
        row_bytes = 2
        for value in row:
            normalized = _bounded_normalize(
                value, max_result_value_bytes=max_result_value_bytes
            )
            row_bytes += _serialized_json_size(normalized) + (
                1 if normalized_row else 0
            )
            if used_bytes + row_bytes + (1 if rows else 0) > max_result_bytes:
                raise ValueError(
                    f"result exceeds max_result_bytes: {max_result_bytes}"
                )
            normalized_row.append(normalized)
        used_bytes += row_bytes + (1 if rows else 0)
        rows.append(normalized_row)
    return {"columns": columns, "rows": rows}


def main(argv: Sequence[str] | None = None) -> int:
    (
        max_json_depth,
        max_params,
        max_result_rows,
        max_result_columns,
        max_result_value_bytes,
        max_result_bytes,
        max_transcript_result_bytes,
        worker_argv,
    ) = _parse_resource_args(argv)
    raw = sys.stdin.buffer.read()
    try:
        _validate_json_depth(raw, max_json_depth=max_json_depth)
    except worker.ProtocolError as exc:
        sys.stderr.write(f"protocol_error: {exc}\n")
        return 2

    replay_stdin = io.TextIOWrapper(io.BytesIO(raw), encoding="utf-8")
    original_stdin = sys.stdin
    original_decode_statement = worker._decode_statement
    original_execute_statement = worker._execute_statement
    transcript_result_bytes = 0

    def bounded_decode(value: Any, *, field: str, max_sql_bytes: int) -> Any:
        return _bounded_decode_statement(
            value,
            field=field,
            max_sql_bytes=max_sql_bytes,
            max_params=max_params,
        )

    def bounded_execute(connection: Any, statement: Any) -> dict[str, Any]:
        nonlocal transcript_result_bytes
        result = _bounded_execute_statement(
            connection,
            statement,
            max_result_rows=max_result_rows,
            max_result_columns=max_result_columns,
            max_result_value_bytes=max_result_value_bytes,
            max_result_bytes=max_result_bytes,
        )
        result_bytes = _serialized_json_size(result)
        if transcript_result_bytes + result_bytes > max_transcript_result_bytes:
            raise ValueError(
                "transaction transcript results exceed "
                f"max_transcript_result_bytes: {max_transcript_result_bytes}"
            )
        transcript_result_bytes += result_bytes
        return result

    sys.stdin = replay_stdin
    worker._decode_statement = bounded_decode
    worker._execute_statement = bounded_execute
    try:
        return worker.main(worker_argv)
    finally:
        worker._decode_statement = original_decode_statement
        worker._execute_statement = original_execute_statement
        sys.stdin = original_stdin


if __name__ == "__main__":
    raise SystemExit(main())
