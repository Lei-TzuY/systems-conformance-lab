from __future__ import annotations

import argparse
import json
import math
import sqlite3
import sys
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import _sqlite_worker as base

_BUSY_ERRORS = {"SQLITE_BUSY", "SQLITE_BUSY_RECOVERY", "SQLITE_BUSY_SNAPSHOT"}
_DISALLOWED_INPUT_KEYWORDS = {
    "attach",
    "begin",
    "commit",
    "detach",
    "end",
    "pragma",
    "release",
    "rollback",
    "savepoint",
}


class ResultBudgetExceeded(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class _Step:
    connection: str
    op: str
    mode: str | None = None
    sql: str | None = None
    params: tuple[Any, ...] = ()


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--journal-mode", choices=("delete", "wal"), required=True)
    parser.add_argument("--max-setup-statements", type=base._positive_int, required=True)
    parser.add_argument("--max-steps", type=base._positive_int, required=True)
    parser.add_argument("--max-sql-bytes", type=base._positive_int, required=True)
    parser.add_argument("--max-total-sql-bytes", type=base._positive_int, required=True)
    parser.add_argument("--max-params", type=base._positive_int, required=True)
    parser.add_argument("--max-result-rows", type=base._positive_int, required=True)
    parser.add_argument("--max-result-columns", type=base._positive_int, required=True)
    parser.add_argument("--max-result-value-bytes", type=base._positive_int, required=True)
    parser.add_argument("--max-result-bytes", type=base._positive_int, required=True)
    parser.add_argument("--max-transcript-bytes", type=base._positive_int, required=True)
    return parser.parse_args(argv)


def _first_sql_keyword(sql: str) -> str:
    index = 0
    length = len(sql)
    while index < length:
        if sql[index].isspace():
            index += 1
            continue
        if sql.startswith("--", index):
            newline = sql.find("\n", index + 2)
            if newline < 0:
                return ""
            index = newline + 1
            continue
        if sql.startswith("/*", index):
            end = sql.find("*/", index + 2)
            if end < 0:
                return ""
            index = end + 2
            continue
        break

    start = index
    while index < length and (sql[index].isalpha() or sql[index] == "_"):
        index += 1
    return sql[start:index].lower()


def _validate_user_sql(sql: Any, *, field: str, max_sql_bytes: int) -> str:
    validated = base._validate_sql(sql, field=field, max_sql_bytes=max_sql_bytes)
    keyword = _first_sql_keyword(validated)
    if keyword in _DISALLOWED_INPUT_KEYWORDS:
        raise base.ProtocolError(f"{field} uses disallowed SQL control: {keyword}")
    return validated


def _validate_param(value: Any) -> None:
    if value is None or isinstance(value, (bool, str)):
        return
    if isinstance(value, int):
        if not -(1 << 63) <= value < (1 << 63):
            raise base.ProtocolError("integer params must fit signed 64-bit SQLite range")
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise base.ProtocolError("floating params must be finite")
        return
    raise base.ProtocolError("params may only contain JSON scalar values")


def _decode_params(value: Any, *, max_params: int) -> tuple[Any, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise base.ProtocolError("params must be a JSON array")
    if len(value) > max_params:
        raise base.ProtocolError(f"params exceeds max_params: {max_params}")
    for item in value:
        _validate_param(item)
    return tuple(value)


def _decode_step(
    value: Any,
    *,
    index: int,
    max_sql_bytes: int,
    max_params: int,
) -> _Step:
    if not isinstance(value, dict):
        raise base.ProtocolError(f"step {index} must be an object")
    connection = value.get("connection")
    op = value.get("op")
    if connection not in {"a", "b"}:
        raise base.ProtocolError(f"step {index} connection must be 'a' or 'b'")
    if not isinstance(op, str):
        raise base.ProtocolError(f"step {index} op must be a string")

    if op in {"begin", "try_begin"}:
        if set(value) != {"connection", "op", "mode"}:
            raise base.ProtocolError(f"step {index} {op} must contain connection, op, and mode")
        mode = value["mode"]
        if mode not in {"deferred", "immediate", "exclusive"}:
            raise base.ProtocolError(
                f"step {index} mode must be deferred, immediate, or exclusive"
            )
        return _Step(connection=connection, op=op, mode=mode)

    if op in {"commit", "rollback"}:
        if set(value) != {"connection", "op"}:
            raise base.ProtocolError(f"step {index} {op} accepts only connection and op")
        return _Step(connection=connection, op=op)

    if op in {"execute", "query", "try_execute", "try_query"}:
        if not {"connection", "op", "sql"} <= set(value):
            raise base.ProtocolError(f"step {index} {op} requires connection, op, and sql")
        if set(value) - {"connection", "op", "sql", "params"}:
            raise base.ProtocolError(f"step {index} {op} contains unknown fields")
        sql = _validate_user_sql(
            value["sql"],
            field=f"step {index} sql",
            max_sql_bytes=max_sql_bytes,
        )
        params = _decode_params(value.get("params"), max_params=max_params)
        return _Step(connection=connection, op=op, sql=sql, params=params)

    raise base.ProtocolError(f"step {index} has unsupported op: {op}")


def _decode_request(
    raw: bytes,
    *,
    max_setup_statements: int,
    max_steps: int,
    max_sql_bytes: int,
    max_total_sql_bytes: int,
    max_params: int,
) -> tuple[list[str], list[_Step]]:
    try:
        payload = json.loads(
            raw.decode("utf-8"),
            parse_constant=base._reject_json_constant,
            object_pairs_hook=base._unique_json_object,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
        raise base.ProtocolError("input must be one UTF-8 JSON document") from exc
    if not isinstance(payload, dict):
        raise base.ProtocolError("top-level request must be an object")
    if set(payload) != {"setup", "steps"}:
        raise base.ProtocolError("request must contain exactly setup and steps")

    setup_value = payload["setup"]
    if not isinstance(setup_value, list) or not all(
        isinstance(item, str) for item in setup_value
    ):
        raise base.ProtocolError("setup must be a list of SQL strings")
    if len(setup_value) > max_setup_statements:
        raise base.ProtocolError(
            f"setup exceeds max_setup_statements: {max_setup_statements}"
        )
    setup = [
        _validate_user_sql(
            statement,
            field="setup statement",
            max_sql_bytes=max_sql_bytes,
        )
        for statement in setup_value
    ]

    steps_value = payload["steps"]
    if not isinstance(steps_value, list) or not steps_value:
        raise base.ProtocolError("steps must be a non-empty list")
    if len(steps_value) > max_steps:
        raise base.ProtocolError(f"steps exceeds max_steps: {max_steps}")
    steps = [
        _decode_step(
            value,
            index=index,
            max_sql_bytes=max_sql_bytes,
            max_params=max_params,
        )
        for index, value in enumerate(steps_value)
    ]

    total_sql_bytes = sum(len(statement.encode("utf-8")) for statement in setup)
    total_sql_bytes += sum(
        len(step.sql.encode("utf-8")) for step in steps if step.sql is not None
    )
    if total_sql_bytes > max_total_sql_bytes:
        raise base.ProtocolError(
            f"request SQL exceeds max_total_sql_bytes: {max_total_sql_bytes}"
        )
    return setup, steps


def _set_journal_mode(connection: sqlite3.Connection, journal_mode: str) -> None:
    row = connection.execute(f"PRAGMA journal_mode = {journal_mode.upper()}").fetchone()
    actual = None if row is None else str(row[0]).lower()
    if actual != journal_mode:
        raise RuntimeError(
            f"SQLite journal mode unavailable: requested {journal_mode}, got {actual}"
        )


def _configure_connection(connection: sqlite3.Connection) -> None:
    base._disable_extension_loading(connection)
    connection.execute("PRAGMA busy_timeout = 0")
    connection.set_authorizer(base._authorizer)


def _begin(connection: sqlite3.Connection, mode: str) -> None:
    connection.execute(f"BEGIN {mode.upper()}")


def _busy_error(exc: sqlite3.OperationalError) -> tuple[str, int]:
    error_name = getattr(exc, "sqlite_errorname", type(exc).__name__)
    if error_name not in _BUSY_ERRORS:
        raise exc
    error_code = getattr(exc, "sqlite_errorcode", None)
    if isinstance(error_code, bool) or not isinstance(error_code, int):
        raise TypeError("SQLite busy error did not expose an integer error code") from exc
    return error_name, error_code


def _normalize_value(value: Any, *, max_result_value_bytes: int) -> Any:
    if isinstance(value, bytes):
        size = len(value)
    elif isinstance(value, str):
        size = len(value.encode("utf-8"))
    else:
        return base._normalize(value)
    if size > max_result_value_bytes:
        raise ResultBudgetExceeded(
            f"result value exceeds max_result_value_bytes: {max_result_value_bytes}"
        )
    return base._normalize(value)


def _json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _collect_query(
    cursor: sqlite3.Cursor,
    *,
    max_result_rows: int,
    max_result_columns: int,
    max_result_value_bytes: int,
    max_result_bytes: int,
) -> tuple[list[str], list[list[Any]]]:
    if cursor.description is None:
        raise base.ProtocolError("query step SQL must return columns")
    if len(cursor.description) > max_result_columns:
        raise ResultBudgetExceeded(
            f"result exceeds max_result_columns: {max_result_columns}"
        )

    columns = [item[0] for item in cursor.description]
    columns_json = _json_bytes(columns)
    used_bytes = len(b'{"columns":') + len(columns_json) + len(b',"rows":[]}')
    if used_bytes > max_result_bytes:
        raise ResultBudgetExceeded(f"result exceeds max_result_bytes: {max_result_bytes}")

    rows: list[list[Any]] = []
    for row in cursor:
        if len(rows) >= max_result_rows:
            raise ResultBudgetExceeded(f"result exceeds max_result_rows: {max_result_rows}")
        normalized = [
            _normalize_value(value, max_result_value_bytes=max_result_value_bytes)
            for value in row
        ]
        row_json = _json_bytes(normalized)
        candidate_size = used_bytes + len(row_json) + (1 if rows else 0)
        if candidate_size > max_result_bytes:
            raise ResultBudgetExceeded(f"result exceeds max_result_bytes: {max_result_bytes}")
        used_bytes = candidate_size
        rows.append(normalized)
    return columns, rows


def _append_record(
    records: list[dict[str, Any]],
    record: dict[str, Any],
    *,
    max_transcript_bytes: int,
) -> None:
    candidate = {"steps": [*records, record]}
    if len(_json_bytes(candidate)) > max_transcript_bytes:
        raise ResultBudgetExceeded(
            f"transcript exceeds max_transcript_bytes: {max_transcript_bytes}"
        )
    records.append(record)


def _run(
    *,
    journal_mode: str,
    setup: list[str],
    steps: list[_Step],
    max_result_rows: int,
    max_result_columns: int,
    max_result_value_bytes: int,
    max_result_bytes: int,
    max_transcript_bytes: int,
) -> bytes:
    with tempfile.TemporaryDirectory(
        prefix="systems-conformance-sqlite-two-connection-"
    ) as directory:
        database = str(Path(directory) / "case.sqlite")
        bootstrap = sqlite3.connect(database, isolation_level=None, timeout=0.0)
        try:
            base._disable_extension_loading(bootstrap)
            _set_journal_mode(bootstrap, journal_mode)
            bootstrap.execute("PRAGMA busy_timeout = 0")
            bootstrap.set_authorizer(base._authorizer)
            for statement in setup:
                bootstrap.execute(statement)
        finally:
            bootstrap.close()

        connections = {
            "a": sqlite3.connect(database, isolation_level=None, timeout=0.0),
            "b": sqlite3.connect(database, isolation_level=None, timeout=0.0),
        }
        records: list[dict[str, Any]] = []
        try:
            for connection in connections.values():
                _configure_connection(connection)

            for step in steps:
                connection = connections[step.connection]
                record: dict[str, Any] = {
                    "connection": step.connection,
                    "op": step.op,
                }

                if step.op == "begin":
                    assert step.mode is not None
                    _begin(connection, step.mode)
                    record["mode"] = step.mode
                elif step.op == "try_begin":
                    assert step.mode is not None
                    record["mode"] = step.mode
                    try:
                        _begin(connection, step.mode)
                    except sqlite3.OperationalError as exc:
                        error_name, _error_code = _busy_error(exc)
                        record["ok"] = False
                        record["error"] = error_name
                    else:
                        record["ok"] = True
                elif step.op == "commit":
                    if not connection.in_transaction:
                        raise RuntimeError(
                            f"connection {step.connection} commit without transaction"
                        )
                    connection.commit()
                elif step.op == "rollback":
                    if not connection.in_transaction:
                        raise RuntimeError(
                            f"connection {step.connection} rollback without transaction"
                        )
                    connection.rollback()
                elif step.op in {"execute", "try_execute"}:
                    assert step.sql is not None
                    try:
                        cursor = connection.execute(step.sql, step.params)
                    except sqlite3.OperationalError as exc:
                        if step.op != "try_execute":
                            raise
                        error_name, error_code = _busy_error(exc)
                        record["ok"] = False
                        record["error"] = error_name
                        record["error_code"] = error_code
                    else:
                        if cursor.description is not None:
                            raise base.ProtocolError("execute step SQL must not return columns")
                        if step.op == "try_execute":
                            record["ok"] = True
                elif step.op in {"query", "try_query"}:
                    assert step.sql is not None
                    try:
                        cursor = connection.execute(step.sql, step.params)
                    except sqlite3.OperationalError as exc:
                        if step.op != "try_query":
                            raise
                        error_name, error_code = _busy_error(exc)
                        record["ok"] = False
                        record["error"] = error_name
                        record["error_code"] = error_code
                    else:
                        columns, rows = _collect_query(
                            cursor,
                            max_result_rows=max_result_rows,
                            max_result_columns=max_result_columns,
                            max_result_value_bytes=max_result_value_bytes,
                            max_result_bytes=max_result_bytes,
                        )
                        if step.op == "try_query":
                            record["ok"] = True
                        record["columns"] = columns
                        record["rows"] = rows
                else:
                    raise AssertionError(f"unhandled step op: {step.op}")

                _append_record(
                    records,
                    record,
                    max_transcript_bytes=max_transcript_bytes,
                )

            active = [name for name, connection in connections.items() if connection.in_transaction]
            if active:
                raise RuntimeError(
                    "scenario ended with active transaction on connection "
                    + ", ".join(active)
                )
            return _json_bytes({"steps": records}) + b"\n"
        finally:
            for connection in connections.values():
                if connection.in_transaction:
                    connection.rollback()
                connection.close()


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    raw = sys.stdin.buffer.read()
    try:
        setup, steps = _decode_request(
            raw,
            max_setup_statements=args.max_setup_statements,
            max_steps=args.max_steps,
            max_sql_bytes=args.max_sql_bytes,
            max_total_sql_bytes=args.max_total_sql_bytes,
            max_params=args.max_params,
        )
        output = _run(
            journal_mode=args.journal_mode,
            setup=setup,
            steps=steps,
            max_result_rows=args.max_result_rows,
            max_result_columns=args.max_result_columns,
            max_result_value_bytes=args.max_result_value_bytes,
            max_result_bytes=args.max_result_bytes,
            max_transcript_bytes=args.max_transcript_bytes,
        )
    except base.ProtocolError as exc:
        sys.stderr.write(f"protocol_error: {exc}\n")
        return 2
    except ResultBudgetExceeded as exc:
        sys.stderr.write(f"result_error: {exc}\n")
        return 4
    except sqlite3.Error as exc:
        error_name = getattr(exc, "sqlite_errorname", type(exc).__name__)
        sys.stderr.write(f"sqlite_scenario_error: {error_name}\n")
        return 3
    except (TypeError, ValueError) as exc:
        sys.stderr.write(f"result_error: {exc}\n")
        return 4
    except RuntimeError as exc:
        sys.stderr.write(f"sqlite_scenario_error: {exc}\n")
        return 3
    sys.stdout.buffer.write(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
