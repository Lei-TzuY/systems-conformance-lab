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
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
        raise ValueError("case must be one UTF-8 JSON document") from exc
    if not isinstance(payload, dict):
        raise TypeError("case must be a JSON object")
    if set(payload) != {"setup", "steps"}:
        raise ValueError("case must contain exactly setup and steps")

    setup = payload["setup"]
    steps = payload["steps"]
    if not isinstance(setup, list) or not all(isinstance(item, str) for item in setup):
        raise TypeError("setup must be a list of SQL strings")
    if not isinstance(steps, list):
        raise TypeError("steps must be a list")
    if not steps:
        raise ValueError("steps must be a non-empty list")
    for step in steps:
        if not isinstance(step, dict):
            raise TypeError("steps must contain JSON objects")
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
    raise TypeError("SQLite scenario params may only contain JSON scalar values")


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
    raise TypeError("SQLite scenario params may only contain JSON scalar values")


def _step_params(step: dict[str, Any], *, index: int) -> list[Any]:
    params = step.get("params", [])
    if not isinstance(params, list):
        raise TypeError(f"step {index} params must be a JSON array")
    for value in params:
        _scalar_complexity(value)
    return params


def sqlite_two_connection_step_count(case: bytes) -> int:
    """Return the number of reducible ordered scenario steps."""
    payload = _decode_case(case)
    steps = payload["steps"]
    assert isinstance(steps, list)
    return len(steps)


def sqlite_two_connection_step_deletions(case: bytes) -> Iterable[bytes]:
    """Yield deterministic step deletions while keeping one scenario step.

    Ordering remains the order present in the retained list. Semantic validity,
    including transaction pairing, remains observable through the real target and
    the reducer's failure-preservation predicate.
    """
    payload = _decode_case(case)
    steps = payload["steps"]
    assert isinstance(steps, list)

    for reduced_steps in _list_deletions(steps, min_items=1):
        candidate = dict(payload)
        candidate["steps"] = reduced_steps
        yield _encode(candidate)


def sqlite_two_connection_setup_count(case: bytes) -> int:
    """Return the number of reducible setup statements."""
    payload = _decode_case(case)
    setup = payload["setup"]
    assert isinstance(setup, list)
    return len(setup)


def sqlite_two_connection_setup_deletions(case: bytes) -> Iterable[bytes]:
    """Yield deterministic setup-statement deletions; setup may become empty."""
    payload = _decode_case(case)
    setup = payload["setup"]
    assert isinstance(setup, list)

    for reduced_setup in _list_deletions(setup, min_items=0):
        candidate = dict(payload)
        candidate["setup"] = reduced_setup
        yield _encode(candidate)


def sqlite_two_connection_parameter_complexity(case: bytes) -> int:
    """Return deterministic scalar complexity across all step parameter arrays."""
    payload = _decode_case(case)
    steps = payload["steps"]
    assert isinstance(steps, list)

    complexity = 0
    for index, step in enumerate(steps):
        assert isinstance(step, dict)
        params = _step_params(step, index=index)
        complexity += sum(_scalar_complexity(value) for value in params)
    return complexity


def sqlite_two_connection_parameter_reductions(case: bytes) -> Iterable[bytes]:
    """Yield one-at-a-time scalar simplifications across ordered step params."""
    payload = _decode_case(case)
    steps = payload["steps"]
    assert isinstance(steps, list)
    current_complexity = sqlite_two_connection_parameter_complexity(case)

    for step_index, step in enumerate(steps):
        assert isinstance(step, dict)
        params = _step_params(step, index=step_index)
        for param_index, value in enumerate(params):
            for replacement in _simpler_scalars(value):
                candidate = dict(payload)
                candidate_steps = list(steps)
                candidate_step = dict(step)
                candidate_params = list(params)
                candidate_params[param_index] = replacement
                candidate_step["params"] = candidate_params
                candidate_steps[step_index] = candidate_step
                candidate["steps"] = candidate_steps
                encoded = _encode(candidate)
                if sqlite_two_connection_parameter_complexity(encoded) < current_complexity:
                    yield encoded
