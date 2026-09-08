from __future__ import annotations

import json
import math
from collections.abc import Sequence
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


def _same_json_scalar(left: Any, right: Any) -> bool:
    return type(left) is type(right) and left == right


def _ordered_replacements(value: Any, candidates: Sequence[Any]) -> tuple[Any, ...]:
    replacements: list[Any] = []
    for candidate in candidates:
        if _same_json_scalar(candidate, value):
            continue
        if any(_same_json_scalar(candidate, existing) for existing in replacements):
            continue
        replacements.append(candidate)
    return tuple(replacements)


def _mutation_values(value: Any) -> tuple[Any, ...]:
    if value is None:
        return _ordered_replacements(value, (0, "", False))
    if isinstance(value, bool):
        return _ordered_replacements(value, (not value, None, 0, 1, "0", "1"))
    if isinstance(value, int):
        if not -(1 << 63) <= value < (1 << 63):
            raise ValueError("integer params must fit signed 64-bit SQLite range")
        return _ordered_replacements(value, (0, 1, -1, None, float(value), str(value), "x"))
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("floating params must be finite")
        return _ordered_replacements(value, (0.0, 1.0, -1.0, None, str(value), "x"))
    if isinstance(value, str):
        return _ordered_replacements(value, ("", "0", "x", None, 0, 1))
    raise TypeError("SQLite query params may only contain JSON scalar values")


def _validate_fault(fault: Any) -> dict[str, Any] | None:
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


def _decode_seed(seed: bytes) -> dict[str, Any]:
    try:
        payload = json.loads(
            seed.decode("utf-8"),
            parse_constant=_reject_json_constant,
            object_pairs_hook=_unique_json_object,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("seed must be one UTF-8 JSON document") from exc
    if not isinstance(payload, dict):
        raise TypeError("seed must be a JSON object")
    if not isinstance(payload.get("query"), str):
        raise TypeError("query must be a string")
    setup = payload.get("setup", [])
    if not isinstance(setup, list) or any(not isinstance(statement, str) for statement in setup):
        raise TypeError("setup must be a list of strings")
    params = payload.get("params", [])
    if not isinstance(params, list):
        raise TypeError("params must be a JSON array")
    for value in params:
        _mutation_values(value)
    _validate_fault(payload.get("fault"))
    return payload


def _encode(payload: dict[str, Any]) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


class SQLiteQueryParameterMutations:
    """Finite deterministic corpus for SQLite query scalar and fault inputs.

    Exact seed bytes are emitted first. Generated cases then walk query parameters in
    index order using type-aware same-type and cross-type replacements, followed by
    bounded fault-occurrence probes at 0, 1, and 2. Query text, setup statements, fault
    operation, and fault kind remain unchanged. Duplicate and oversized cases are
    skipped, so the source is deterministic and safe for bounded fuzz campaigns.
    """

    __slots__ = ("_cases",)

    def __init__(self, seeds: Sequence[bytes], *, max_case_bytes: int = 65536) -> None:
        if isinstance(max_case_bytes, bool) or not isinstance(max_case_bytes, int):
            raise TypeError("max_case_bytes must be an integer")
        if max_case_bytes <= 0:
            raise ValueError("max_case_bytes must be positive")
        if not seeds:
            raise ValueError("seeds must be non-empty")

        cases: list[bytes] = []
        seen: set[bytes] = set()
        decoded: list[dict[str, Any]] = []
        for seed in seeds:
            if not isinstance(seed, bytes):
                raise TypeError("seeds must contain bytes")
            if len(seed) > max_case_bytes:
                raise ValueError("seed exceeds max_case_bytes")
            payload = _decode_seed(seed)
            decoded.append(payload)
            if seed not in seen:
                cases.append(seed)
                seen.add(seed)

        for payload in decoded:
            params = payload.get("params", [])
            assert isinstance(params, list)
            for param_index, value in enumerate(params):
                for replacement in _mutation_values(value):
                    candidate = dict(payload)
                    candidate_params = list(params)
                    candidate_params[param_index] = replacement
                    candidate["params"] = candidate_params
                    encoded = _encode(candidate)
                    if len(encoded) > max_case_bytes or encoded in seen:
                        continue
                    cases.append(encoded)
                    seen.add(encoded)

            fault = _validate_fault(payload.get("fault"))
            if fault is not None:
                occurrence = fault["occurrence"]
                for replacement in (0, 1, 2):
                    if replacement == occurrence:
                        continue
                    candidate = dict(payload)
                    candidate_fault = dict(fault)
                    candidate_fault["occurrence"] = replacement
                    candidate["fault"] = candidate_fault
                    encoded = _encode(candidate)
                    if len(encoded) > max_case_bytes or encoded in seen:
                        continue
                    cases.append(encoded)
                    seen.add(encoded)

        self._cases = tuple(cases)

    @property
    def case_count(self) -> int:
        return len(self._cases)

    def __len__(self) -> int:
        return self.case_count

    def __getitem__(self, index: int) -> bytes:
        return self._cases[index]

    def __call__(self, index: int) -> bytes:
        if index < 0:
            raise ValueError("index must be non-negative")
        try:
            return self._cases[index]
        except IndexError as exc:
            raise IndexError("mutation schedule exhausted") from exc
