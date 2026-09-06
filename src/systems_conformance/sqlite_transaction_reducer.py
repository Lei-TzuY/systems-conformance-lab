from __future__ import annotations

import json
import math
from collections.abc import Iterable
from typing import Any, Literal


def _reject_json_constant(value: str) -> Any:
    raise ValueError(f"non-finite JSON constant is not supported: {value}")


def _unique_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON object field: {key}")
        result[key] = value
    return result


def _decode_case(case: bytes) -> dict[str, Any]:
    try:
        payload = json.loads(
            case.decode("utf-8"),
            parse_constant=_reject_json_constant,
            object_pairs_hook=_unique_json_object,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("case must be one UTF-8 JSON document") from exc
    if not isinstance(payload, dict):
        raise TypeError("case must be a JSON object")

    setup = payload.get("setup", [])
    transaction = payload.get("transaction")
    if not isinstance(setup, list):
        raise TypeError("setup must be a list")
    if not isinstance(transaction, list):
        raise TypeError("transaction must be a list")
    if not transaction:
        raise ValueError("transaction must be a non-empty list")
    return payload


def _encode(payload: dict[str, Any]) -> bytes:
    try:
        return json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ValueError("case must contain JSON-serializable finite values") from exc


def _list_deletions(values: list[Any], *, min_items: int) -> Iterable[list[Any]]:
    length = len(values)
    removable = length - min_items
    if removable <= 0:
        return

    width = 1 << (removable.bit_length() - 1)
    seen: set[str] = set()
    while width >= 1:
        for start in range(0, length, width):
            end = min(start + width, length)
            if length - (end - start) < min_items:
                continue
            candidate = values[:start] + values[end:]
            key = json.dumps(
                candidate,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
            if key in seen:
                continue
            seen.add(key)
            yield candidate
        width //= 2


def _scalar_complexity(value: Any) -> int:
    if value is None:
        return 0
    if isinstance(value, bool):
        return 2 if value else 1
    if isinstance(value, int):
        if not -(1 << 63) <= value < (1 << 63):
            raise ValueError("integer params must fit signed 64-bit SQLite range")
        return 3 + min(abs(value), 1_000_000)
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("floating params must be finite")
        return 1_000_004 + min(int(abs(value) * 1_000), 1_000_000)
    if isinstance(value, str):
        return 2_000_005 + len(value.encode("utf-8"))
    raise TypeError("SQLite statement params may only contain JSON scalar values")


def _simpler_scalars(value: Any) -> tuple[Any, ...]:
    if value is None:
        return ()
    if isinstance(value, bool):
        return (False, None) if value else (None,)
    if isinstance(value, int):
        _scalar_complexity(value)
        boundary = -1 if value < 0 else 1
        values = (0, boundary, None) if abs(value) > 1 else (0, None)
        return tuple(candidate for candidate in values if candidate != value)
    if isinstance(value, float):
        _scalar_complexity(value)
        boundary = -1.0 if value < 0 else 1.0
        values = (0.0, boundary, None) if abs(value) > 1.0 else (0.0, None)
        return tuple(candidate for candidate in values if candidate != value)
    if isinstance(value, str):
        values = ("", "0", None) if len(value) > 1 else ("", None)
        return tuple(candidate for candidate in values if candidate != value)
    raise TypeError("SQLite statement params may only contain JSON scalar values")


def _parameter_sections(
    payload: dict[str, Any],
) -> Iterable[tuple[Literal["transaction", "observe"], int | None, dict[str, Any]]]:
    transaction = payload["transaction"]
    assert isinstance(transaction, list)
    for statement_index, statement in enumerate(transaction):
        if not isinstance(statement, dict):
            raise TypeError("transaction statements must be JSON objects")
        yield "transaction", statement_index, statement

    observe = payload.get("observe")
    if not isinstance(observe, dict):
        raise TypeError("observe must be a JSON object")
    yield "observe", None, observe


def _statement_params(statement: dict[str, Any], *, field: str) -> list[Any]:
    params = statement.get("params", [])
    if not isinstance(params, list):
        raise TypeError(f"{field} params must be a JSON array")
    for value in params:
        _scalar_complexity(value)
    return params


def _fault(payload: dict[str, Any]) -> dict[str, Any] | None:
    fault = payload.get("fault")
    if fault is None:
        return None
    if not isinstance(fault, dict):
        raise TypeError("fault must be a JSON object")
    if set(fault) != {"operation", "occurrence", "kind"}:
        raise ValueError("fault must contain operation, occurrence, and kind")
    if fault["operation"] not in {"setup", "transaction", "finalize", "observe"}:
        raise ValueError("fault operation is unsupported")
    occurrence = fault["occurrence"]
    if isinstance(occurrence, bool) or not isinstance(occurrence, int) or occurrence < 0:
        raise ValueError("fault occurrence must be a non-negative integer")
    if fault["kind"] != "abort":
        raise ValueError("fault kind is unsupported")
    return fault


def sqlite_transaction_statement_count(case: bytes) -> int:
    """Return the reducible setup + transaction statement count for one case."""
    payload = _decode_case(case)
    setup = payload.get("setup", [])
    transaction = payload["transaction"]
    assert isinstance(setup, list)
    assert isinstance(transaction, list)
    return len(setup) + len(transaction)


def sqlite_transaction_statement_deletions(case: bytes) -> Iterable[bytes]:
    """Yield deterministic valid-shape statement deletion candidates.

    Transaction statements are reduced before setup statements because they are the
    primary behavior under test. At least one transaction statement is always kept;
    setup may reduce to empty. Other request fields, including observation and fault
    specifications, are preserved verbatim at the decoded JSON-value level. Semantic
    validity remains the target's responsibility and is checked by the reducer's
    failure-preservation predicate.
    """
    payload = _decode_case(case)
    setup = payload.get("setup", [])
    transaction = payload["transaction"]
    assert isinstance(setup, list)
    assert isinstance(transaction, list)

    for reduced_transaction in _list_deletions(transaction, min_items=1):
        candidate = dict(payload)
        candidate["transaction"] = reduced_transaction
        yield _encode(candidate)

    for reduced_setup in _list_deletions(setup, min_items=0):
        candidate = dict(payload)
        candidate["setup"] = reduced_setup
        yield _encode(candidate)


def sqlite_transaction_parameter_complexity(case: bytes) -> int:
    """Return deterministic scalar complexity across transaction and observe params."""
    payload = _decode_case(case)
    complexity = 0
    for section, _, statement in _parameter_sections(payload):
        params = _statement_params(statement, field=section)
        complexity += sum(_scalar_complexity(value) for value in params)
    return complexity


def sqlite_transaction_parameter_reductions(case: bytes) -> Iterable[bytes]:
    """Yield deterministic scalar simplifications while preserving request shape.

    Transaction parameters are considered before observation parameters. Only one
    scalar is changed per candidate, and unrelated statements, SQL text, faults, and
    request fields are preserved. Candidate validity remains observable through the
    real target and failure-preservation predicate.
    """
    payload = _decode_case(case)
    current_complexity = sqlite_transaction_parameter_complexity(case)

    for section, statement_index, statement in _parameter_sections(payload):
        params = _statement_params(statement, field=section)
        for param_index, value in enumerate(params):
            for replacement in _simpler_scalars(value):
                candidate = dict(payload)
                candidate_statement = dict(statement)
                candidate_params = list(params)
                candidate_params[param_index] = replacement
                candidate_statement["params"] = candidate_params

                if section == "transaction":
                    assert statement_index is not None
                    transaction = payload["transaction"]
                    assert isinstance(transaction, list)
                    candidate_transaction = list(transaction)
                    candidate_transaction[statement_index] = candidate_statement
                    candidate["transaction"] = candidate_transaction
                else:
                    candidate["observe"] = candidate_statement

                encoded = _encode(candidate)
                if sqlite_transaction_parameter_complexity(encoded) < current_complexity:
                    yield encoded


def sqlite_transaction_fault_occurrence_complexity(case: bytes) -> int:
    """Return the non-negative occurrence index for an optional SQLite fault."""
    payload = _decode_case(case)
    fault = _fault(payload)
    if fault is None:
        return 0
    occurrence = fault["occurrence"]
    assert isinstance(occurrence, int) and not isinstance(occurrence, bool)
    return occurrence


def sqlite_transaction_fault_occurrence_reductions(case: bytes) -> Iterable[bytes]:
    """Yield bounded lower fault-occurrence probes while preserving fault identity.

    The operation and kind remain unchanged and only ``occurrence`` is rewritten.
    Candidates use the same early-checkpoint boundary values exercised by the
    deterministic fuzz corpus and are emitted only when they strictly decrease the
    explicit occurrence complexity measure.
    """
    payload = _decode_case(case)
    fault = _fault(payload)
    if fault is None:
        return

    current = sqlite_transaction_fault_occurrence_complexity(case)
    for replacement in (0, 1, 2):
        if replacement >= current:
            continue
        candidate = dict(payload)
        candidate_fault = dict(fault)
        candidate_fault["occurrence"] = replacement
        candidate["fault"] = candidate_fault
        encoded = _encode(candidate)
        if sqlite_transaction_fault_occurrence_complexity(encoded) < current:
            yield encoded
