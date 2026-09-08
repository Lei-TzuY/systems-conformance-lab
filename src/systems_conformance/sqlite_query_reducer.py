from __future__ import annotations

import json
import math
from collections.abc import Iterable
from typing import Any


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
    query = payload.get("query")
    params = payload.get("params", [])
    if not isinstance(setup, list):
        raise TypeError("setup must be a list")
    if not isinstance(query, str):
        raise TypeError("query must be a string")
    if not isinstance(params, list):
        raise TypeError("params must be a JSON array")
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


def _list_deletions(values: list[Any]) -> Iterable[list[Any]]:
    length = len(values)
    if length == 0:
        return

    width = 1 << (length.bit_length() - 1)
    seen: set[str] = set()
    while width >= 1:
        for start in range(0, length, width):
            end = min(start + width, length)
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
    raise TypeError("SQLite query params may only contain JSON scalar values")


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
    raise TypeError("SQLite query params may only contain JSON scalar values")


def _params(payload: dict[str, Any]) -> list[Any]:
    params = payload.get("params", [])
    assert isinstance(params, list)
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
    if fault["operation"] not in {"setup", "query"}:
        raise ValueError("fault operation is unsupported")
    occurrence = fault["occurrence"]
    if isinstance(occurrence, bool) or not isinstance(occurrence, int) or occurrence < 0:
        raise ValueError("fault occurrence must be a non-negative integer")
    if fault["kind"] != "abort":
        raise ValueError("fault kind is unsupported")
    return fault


def sqlite_query_setup_statement_count(case: bytes) -> int:
    """Return the number of reducible setup statements in one query case."""
    payload = _decode_case(case)
    setup = payload.get("setup", [])
    assert isinstance(setup, list)
    return len(setup)


def sqlite_query_setup_statement_deletions(case: bytes) -> Iterable[bytes]:
    """Yield deterministic setup-statement deletions while preserving the query."""
    payload = _decode_case(case)
    setup = payload.get("setup", [])
    assert isinstance(setup, list)

    for reduced_setup in _list_deletions(setup):
        candidate = dict(payload)
        candidate["setup"] = reduced_setup
        yield _encode(candidate)


def sqlite_query_parameter_complexity(case: bytes) -> int:
    """Return deterministic scalar complexity across query parameters."""
    payload = _decode_case(case)
    return sum(_scalar_complexity(value) for value in _params(payload))


def sqlite_query_parameter_reductions(case: bytes) -> Iterable[bytes]:
    """Yield deterministic one-at-a-time scalar query-parameter simplifications."""
    payload = _decode_case(case)
    params = _params(payload)
    current_complexity = sqlite_query_parameter_complexity(case)

    for param_index, value in enumerate(params):
        for replacement in _simpler_scalars(value):
            candidate = dict(payload)
            candidate_params = list(params)
            candidate_params[param_index] = replacement
            candidate["params"] = candidate_params
            encoded = _encode(candidate)
            if sqlite_query_parameter_complexity(encoded) < current_complexity:
                yield encoded


def sqlite_query_fault_occurrence_complexity(case: bytes) -> int:
    """Return the non-negative occurrence index for an optional SQLite query fault."""
    payload = _decode_case(case)
    fault = _fault(payload)
    if fault is None:
        return 0
    occurrence = fault["occurrence"]
    assert isinstance(occurrence, int) and not isinstance(occurrence, bool)
    return occurrence


def sqlite_query_fault_occurrence_reductions(case: bytes) -> Iterable[bytes]:
    """Yield bounded lower fault-occurrence probes while preserving fault identity."""
    payload = _decode_case(case)
    fault = _fault(payload)
    if fault is None:
        return

    current = sqlite_query_fault_occurrence_complexity(case)
    for replacement in (0, 1, 2):
        if replacement >= current:
            continue
        candidate = dict(payload)
        candidate_fault = dict(fault)
        candidate_fault["occurrence"] = replacement
        candidate["fault"] = candidate_fault
        encoded = _encode(candidate)
        if sqlite_query_fault_occurrence_complexity(encoded) < current:
            yield encoded
