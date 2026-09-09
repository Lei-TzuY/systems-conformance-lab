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

from .fault import FaultController, FaultSpec


class ProtocolError(ValueError):
    pass


class InjectedFault(RuntimeError):
    def __init__(self, spec: FaultSpec) -> None:
        self.spec = spec
        super().__init__(f"{spec.kind} {spec.operation} {spec.occurrence}")


class VmBudgetExceeded(RuntimeError):
    def __init__(self, max_vm_steps: int) -> None:
        self.max_vm_steps = max_vm_steps
        super().__init__(str(max_vm_steps))


@dataclass(frozen=True, slots=True)
class _Statement:
    sql: str
    params: list[Any]


@dataclass(slots=True)
class _VmBudget:
    remaining: int
    exhausted: bool = False

    def progress(self) -> int:
        self.remaining -= 1
        if self.remaining <= 0:
            self.exhausted = True
            return 1
        return 0


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return parsed


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(add_help=False)
    finalize = parser.add_mutually_exclusive_group(required=True)
    finalize.add_argument("--commit", action="store_true")
    finalize.add_argument("--rollback", action="store_true")
    foreign_keys = parser.add_mutually_exclusive_group(required=True)
    foreign_keys.add_argument("--foreign-keys", action="store_true")
    foreign_keys.add_argument("--no-foreign-keys", action="store_true")
    faults = parser.add_mutually_exclusive_group(required=True)
    faults.add_argument("--enable-faults", action="store_true")
    faults.add_argument("--disable-faults", action="store_true")
    persistence = parser.add_mutually_exclusive_group(required=True)
    persistence.add_argument("--reopen-before-observe", action="store_true")
    persistence.add_argument("--same-connection-observe", action="store_true")
    parser.add_argument("--journal-mode", choices=("delete", "wal"), default="delete")
    parser.add_argument("--synchronous", choices=("normal", "full"), default="full")
    parser.add_argument("--max-statements", required=True, type=_positive_int)
    parser.add_argument("--max-sql-bytes", required=True, type=_positive_int)
    parser.add_argument("--max-vm-steps", type=_positive_int)
    return parser.parse_args(argv)


def _reject_json_constant(value: str) -> Any:
    raise ProtocolError(f"non-finite JSON constant is not supported: {value}")


def _unique_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ProtocolError(f"duplicate JSON object field: {key}")
        result[key] = value
    return result


def _validate_params(params: Any) -> list[Any]:
    if not isinstance(params, list):
        raise ProtocolError("statement params must be a JSON array")
    for value in params:
        if value is None or isinstance(value, (bool, str)):
            continue
        if isinstance(value, int):
            if not -(1 << 63) <= value < (1 << 63):
                raise ProtocolError("integer params must fit signed 64-bit SQLite range")
            continue
        if isinstance(value, float):
            if not math.isfinite(value):
                raise ProtocolError("floating params must be finite")
            continue
        raise ProtocolError("statement params may only contain JSON scalar values")
    return params


def _validate_sql(sql: Any, *, field: str, max_sql_bytes: int) -> str:
    if not isinstance(sql, str) or not sql.strip():
        raise ProtocolError(f"{field} statement sql must be a non-empty string")
    if len(sql.encode("utf-8")) > max_sql_bytes:
        raise ProtocolError(f"{field} statement sql exceeds max_sql_bytes: {max_sql_bytes}")
    return sql


def _decode_statement(value: Any, *, field: str, max_sql_bytes: int) -> _Statement:
    if not isinstance(value, dict):
        raise ProtocolError(f"{field} statement must be an object")
    if set(value) - {"sql", "params"}:
        raise ProtocolError(f"{field} statement contains unknown fields")
    sql = _validate_sql(value.get("sql"), field=field, max_sql_bytes=max_sql_bytes)
    params = _validate_params(value.get("params", []))
    return _Statement(sql=sql, params=params)


def _decode_fault(value: Any) -> FaultSpec | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ProtocolError("fault must be an object")
    if set(value) != {"operation", "occurrence", "kind"}:
        raise ProtocolError("fault must contain operation, occurrence, and kind")

    operation = value["operation"]
    occurrence = value["occurrence"]
    kind = value["kind"]
    if operation not in {"setup", "transaction", "finalize", "observe"}:
        raise ProtocolError(
            "fault operation must be setup, transaction, finalize, or observe"
        )
    if isinstance(occurrence, bool) or not isinstance(occurrence, int) or occurrence < 0:
        raise ProtocolError("fault occurrence must be a non-negative integer")
    if kind != "abort":
        raise ProtocolError("unsupported SQLite transaction fault kind")
    return FaultSpec(operation=operation, occurrence=occurrence, kind=kind)


def _decode_request(
    raw: bytes, *, max_statements: int, max_sql_bytes: int
) -> tuple[list[str], list[_Statement], _Statement, FaultSpec | None]:
    try:
        payload = json.loads(
            raw.decode("utf-8"),
            parse_constant=_reject_json_constant,
            object_pairs_hook=_unique_json_object,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProtocolError("input must be one UTF-8 JSON document") from exc
    if not isinstance(payload, dict):
        raise ProtocolError("top-level request must be an object")
    if set(payload) - {"setup", "transaction", "observe", "fault"}:
        raise ProtocolError("request contains unknown fields")

    setup = payload.get("setup", [])
    transaction = payload.get("transaction")
    observe = payload.get("observe")
    fault = _decode_fault(payload.get("fault"))
    if not isinstance(setup, list) or not all(isinstance(item, str) for item in setup):
        raise ProtocolError("setup must be a list of SQL strings")
    validated_setup = [
        _validate_sql(item, field="setup", max_sql_bytes=max_sql_bytes) for item in setup
    ]
    if not isinstance(transaction, list) or not transaction:
        raise ProtocolError("transaction must be a non-empty list of statement objects")
    decoded_transaction = [
        _decode_statement(item, field="transaction", max_sql_bytes=max_sql_bytes)
        for item in transaction
    ]
    decoded_observe = _decode_statement(
        observe, field="observe", max_sql_bytes=max_sql_bytes
    )
    if len(validated_setup) + len(decoded_transaction) + 1 > max_statements:
        raise ProtocolError(f"request exceeds max_statements: {max_statements}")
    return validated_setup, decoded_transaction, decoded_observe, fault


def _authorizer(
    action: int,
    _arg1: str | None,
    _arg2: str | None,
    _db: str | None,
    _source: str | None,
) -> int:
    forbidden = {
        sqlite3.SQLITE_ATTACH,
        sqlite3.SQLITE_DETACH,
        sqlite3.SQLITE_PRAGMA,
        sqlite3.SQLITE_TRANSACTION,
    }
    return sqlite3.SQLITE_DENY if action in forbidden else sqlite3.SQLITE_OK


def _normalize(value: Any) -> Any:
    if isinstance(value, bytes):
        return {"$blob": value.hex()}
    if value is None or isinstance(value, (int, float, str)):
        return value
    raise TypeError(f"unsupported SQLite result type: {type(value).__name__}")


def _disable_extension_loading(connection: sqlite3.Connection) -> None:
    disable = getattr(connection, "enable_load_extension", None)
    if disable is not None:
        disable(False)


def _configure_connection(
    connection: sqlite3.Connection,
    *,
    foreign_keys: bool,
    budget: _VmBudget | None,
) -> None:
    _disable_extension_loading(connection)
    connection.execute(f"PRAGMA foreign_keys = {'ON' if foreign_keys else 'OFF'}")
    connection.set_authorizer(_authorizer)
    if budget is not None:
        connection.set_progress_handler(budget.progress, 1)


def _configure_journal_mode(connection: sqlite3.Connection, journal_mode: str) -> None:
    row = connection.execute(f"PRAGMA journal_mode = {journal_mode.upper()}").fetchone()
    actual = None if row is None else str(row[0]).lower()
    if actual == "memory" and journal_mode == "delete":
        return
    if actual != journal_mode:
        raise RuntimeError(
            f"SQLite journal mode unavailable: requested {journal_mode}, got {actual}"
        )


def _configure_synchronous(connection: sqlite3.Connection, synchronous: str) -> None:
    expected = {"normal": 1, "full": 2}[synchronous]
    connection.execute(f"PRAGMA synchronous = {synchronous.upper()}")
    row = connection.execute("PRAGMA synchronous").fetchone()
    actual = None if row is None else int(row[0])
    if actual != expected:
        raise RuntimeError(
            f"SQLite synchronous mode unavailable: requested {synchronous}, got {actual}"
        )


def _checkpoint(controller: FaultController | None, operation: str) -> None:
    if controller is None:
        return
    triggered = controller.checkpoint(operation)
    if triggered is not None:
        raise InjectedFault(triggered)


def _execute_statement(connection: sqlite3.Connection, statement: _Statement) -> dict[str, Any]:
    cursor = connection.execute(statement.sql, statement.params)
    columns = [] if cursor.description is None else [item[0] for item in cursor.description]
    rows = [[_normalize(value) for value in row] for row in cursor.fetchall()]
    return {"columns": columns, "rows": rows}


def _run(
    raw: bytes,
    *,
    commit: bool,
    foreign_keys: bool,
    enable_faults: bool,
    reopen_before_observe: bool,
    journal_mode: str,
    synchronous: str,
    max_statements: int,
    max_sql_bytes: int,
    max_vm_steps: int | None,
) -> bytes:
    setup, transaction, observe, fault = _decode_request(
        raw,
        max_statements=max_statements,
        max_sql_bytes=max_sql_bytes,
    )
    controller = FaultController(fault) if enable_faults and fault is not None else None
    budget = _VmBudget(max_vm_steps) if max_vm_steps is not None else None

    temporary_directory: tempfile.TemporaryDirectory[str] | None = None
    database = ":memory:"
    if reopen_before_observe or journal_mode == "wal":
        temporary_directory = tempfile.TemporaryDirectory(
            prefix="systems-conformance-sqlite-"
        )
        database = str(Path(temporary_directory.name) / "case.sqlite")

    connection = sqlite3.connect(database, isolation_level=None)
    try:
        _configure_journal_mode(connection, journal_mode)
        _configure_synchronous(connection, synchronous)
        _configure_connection(connection, foreign_keys=foreign_keys, budget=budget)
        try:
            for statement in setup:
                _checkpoint(controller, "setup")
                connection.execute(statement)

            connection.set_authorizer(None)
            connection.execute("BEGIN")
            connection.set_authorizer(_authorizer)

            transcript = []
            for statement in transaction:
                _checkpoint(controller, "transaction")
                transcript.append(_execute_statement(connection, statement))

            _checkpoint(controller, "finalize")
            connection.set_authorizer(None)
            if commit:
                connection.commit()
            else:
                connection.rollback()
            connection.set_authorizer(_authorizer)

            if reopen_before_observe:
                connection.close()
                connection = sqlite3.connect(database, isolation_level=None)
                _configure_journal_mode(connection, journal_mode)
                _configure_synchronous(connection, synchronous)
                _configure_connection(connection, foreign_keys=foreign_keys, budget=budget)

            _checkpoint(controller, "observe")
            observation = _execute_statement(connection, observe)
        except sqlite3.Error as exc:
            if budget is not None and budget.exhausted:
                raise VmBudgetExceeded(max_vm_steps) from exc
            raise

        payload = {"transaction": transcript, "observation": observation}
        return (
            json.dumps(payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
            + "\n"
        ).encode("utf-8")
    finally:
        connection.close()
        if temporary_directory is not None:
            temporary_directory.cleanup()


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        output = _run(
            sys.stdin.buffer.read(),
            commit=args.commit,
            foreign_keys=args.foreign_keys,
            enable_faults=args.enable_faults,
            reopen_before_observe=args.reopen_before_observe,
            journal_mode=args.journal_mode,
            synchronous=args.synchronous,
            max_statements=args.max_statements,
            max_sql_bytes=args.max_sql_bytes,
            max_vm_steps=args.max_vm_steps,
        )
    except ProtocolError as exc:
        sys.stderr.write(f"protocol_error: {exc}\n")
        return 2
    except InjectedFault as exc:
        sys.stderr.write(f"injected_fault: {exc}\n")
        return 5
    except VmBudgetExceeded as exc:
        sys.stderr.write(f"sqlite_vm_budget_exceeded: {exc.max_vm_steps}\n")
        return 6
    except sqlite3.Error as exc:
        error_name = getattr(exc, "sqlite_errorname", type(exc).__name__)
        sys.stderr.write(f"sqlite_error: {error_name}\n")
        return 3
    except (RuntimeError, TypeError, ValueError) as exc:
        sys.stderr.write(f"result_error: {exc}\n")
        return 4
    sys.stdout.buffer.write(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())