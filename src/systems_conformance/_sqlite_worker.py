from __future__ import annotations

import argparse
import json
import math
import sqlite3
import sys
from collections.abc import Sequence
from dataclasses import dataclass
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


class ResultRowBudgetExceeded(RuntimeError):
    def __init__(self, max_result_rows: int) -> None:
        self.max_result_rows = max_result_rows
        super().__init__(str(max_result_rows))


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
    foreign_keys = parser.add_mutually_exclusive_group(required=True)
    foreign_keys.add_argument("--foreign-keys", action="store_true")
    foreign_keys.add_argument("--no-foreign-keys", action="store_true")
    faults = parser.add_mutually_exclusive_group(required=True)
    faults.add_argument("--enable-faults", action="store_true")
    faults.add_argument("--disable-faults", action="store_true")
    parser.add_argument("--max-sql-bytes", required=True, type=_positive_int)
    parser.add_argument("--max-setup-statements", required=True, type=_positive_int)
    parser.add_argument("--max-result-columns", required=True, type=_positive_int)
    parser.add_argument("--max-result-rows", required=True, type=_positive_int)
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
    if operation not in {"setup", "query"}:
        raise ProtocolError("fault operation must be setup or query")
    if isinstance(occurrence, bool) or not isinstance(occurrence, int) or occurrence < 0:
        raise ProtocolError("fault occurrence must be a non-negative integer")
    if kind != "abort":
        raise ProtocolError("unsupported SQLite fault kind")
    return FaultSpec(operation=operation, occurrence=occurrence, kind=kind)


def _validate_sql(sql: Any, *, field: str, max_sql_bytes: int) -> str:
    if not isinstance(sql, str) or not sql.strip():
        raise ProtocolError(f"{field} must be a non-empty SQL string")
    if len(sql.encode("utf-8")) > max_sql_bytes:
        raise ProtocolError(f"{field} exceeds max_sql_bytes: {max_sql_bytes}")
    return sql


def _decode_request(
    raw: bytes, *, max_sql_bytes: int, max_setup_statements: int
) -> tuple[list[str], str, list[Any], FaultSpec | None]:
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
    if set(payload) - {"setup", "query", "params", "fault"}:
        raise ProtocolError("request contains unknown fields")

    setup = payload.get("setup", [])
    query = payload.get("query")
    params = payload.get("params", [])
    fault = _decode_fault(payload.get("fault"))
    if not isinstance(setup, list) or not all(isinstance(item, str) for item in setup):
        raise ProtocolError("setup must be a list of SQL strings")
    if len(setup) > max_setup_statements:
        raise ProtocolError(f"setup exceeds max_setup_statements: {max_setup_statements}")
    setup = [
        _validate_sql(statement, field="setup statement", max_sql_bytes=max_sql_bytes)
        for statement in setup
    ]
    query = _validate_sql(query, field="query", max_sql_bytes=max_sql_bytes)
    if not isinstance(params, list):
        raise ProtocolError("params must be a JSON array")
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
        raise ProtocolError("params may only contain JSON scalar values")
    return setup, query, params, fault


def _authorizer(
    action: int,
    _arg1: str | None,
    _arg2: str | None,
    _db: str | None,
    _source: str | None,
) -> int:
    forbidden = {sqlite3.SQLITE_ATTACH, sqlite3.SQLITE_DETACH, sqlite3.SQLITE_PRAGMA}
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


def _checkpoint(controller: FaultController | None, operation: str) -> None:
    if controller is None:
        return
    triggered = controller.checkpoint(operation)
    if triggered is not None:
        raise InjectedFault(triggered)


def _collect_rows(cursor: sqlite3.Cursor, *, max_result_rows: int) -> list[list[Any]]:
    rows: list[list[Any]] = []
    for row in cursor:
        if len(rows) >= max_result_rows:
            raise ResultRowBudgetExceeded(max_result_rows)
        rows.append([_normalize(value) for value in row])
    return rows


def _run(
    raw: bytes,
    *,
    foreign_keys: bool,
    enable_faults: bool,
    max_sql_bytes: int,
    max_setup_statements: int,
    max_result_columns: int,
    max_result_rows: int,
    max_vm_steps: int | None,
) -> bytes:
    setup, query, params, fault = _decode_request(
        raw,
        max_sql_bytes=max_sql_bytes,
        max_setup_statements=max_setup_statements,
    )
    controller = FaultController(fault) if enable_faults and fault is not None else None
    budget = _VmBudget(max_vm_steps) if max_vm_steps is not None else None
    connection = sqlite3.connect(":memory:")
    try:
        _disable_extension_loading(connection)
        connection.execute(f"PRAGMA foreign_keys = {'ON' if foreign_keys else 'OFF'}")
        connection.set_authorizer(_authorizer)
        if budget is not None:
            connection.set_progress_handler(budget.progress, 1)
        try:
            for statement in setup:
                _checkpoint(controller, "setup")
                connection.execute(statement)
            _checkpoint(controller, "query")
            cursor = connection.execute(query, params)
            if cursor.description is None:
                columns = []
            else:
                if len(cursor.description) > max_result_columns:
                    raise ValueError(
                        f"result exceeds max_result_columns: {max_result_columns}"
                    )
                columns = [item[0] for item in cursor.description]
            rows = _collect_rows(cursor, max_result_rows=max_result_rows)
        except sqlite3.Error as exc:
            if budget is not None and budget.exhausted:
                raise VmBudgetExceeded(max_vm_steps) from exc
            raise
        payload = {"columns": columns, "rows": rows}
        return (
            json.dumps(payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
            + "\n"
        ).encode("utf-8")
    finally:
        connection.close()


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        output = _run(
            sys.stdin.buffer.read(),
            foreign_keys=args.foreign_keys,
            enable_faults=args.enable_faults,
            max_sql_bytes=args.max_sql_bytes,
            max_setup_statements=args.max_setup_statements,
            max_result_columns=args.max_result_columns,
            max_result_rows=args.max_result_rows,
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
    except ResultRowBudgetExceeded as exc:
        sys.stderr.write(f"result_error: result exceeds max_result_rows: {exc.max_result_rows}\n")
        return 4
    except sqlite3.Error as exc:
        error_name = getattr(exc, "sqlite_errorname", type(exc).__name__)
        sys.stderr.write(f"sqlite_error: {error_name}\n")
        return 3
    except (TypeError, ValueError) as exc:
        sys.stderr.write(f"result_error: {exc}\n")
        return 4
    sys.stdout.buffer.write(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
