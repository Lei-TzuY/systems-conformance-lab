from __future__ import annotations

import json
import math
from collections.abc import Sequence
from typing import Any

_MODES = ("deferred", "immediate", "exclusive")
_SQL_OPS = {"execute", "query", "try_execute", "try_query"}
_BEGIN_OPS = {"begin", "try_begin"}
_SIMPLE_OPS = {"commit", "rollback"}
_ALL_OPS = _SQL_OPS | _BEGIN_OPS | _SIMPLE_OPS


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
        return _ordered_replacements(value, (not value, None, 0, 1))
    if isinstance(value, int):
        if not -(1 << 63) <= value < (1 << 63):
            raise ValueError("integer params must fit signed 64-bit SQLite range")
        return _ordered_replacements(
            value,
            (0, 1, -1, None, float(value), str(value)),
        )
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("floating params must be finite")
        return _ordered_replacements(
            value,
            (0.0, 1.0, -1.0, None, str(value)),
        )
    if isinstance(value, str):
        return _ordered_replacements(value, ("", "0", None, 0, 1))
    raise TypeError("SQLite scenario params may only contain JSON scalar values")


def _validate_params(value: Any, *, step_index: int) -> list[Any]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise TypeError(f"step {step_index} params must be a JSON array")
    for item in value:
        _mutation_values(item)
    return value


def _decode_seed(seed: bytes) -> dict[str, Any]:
    try:
        payload = json.loads(
            seed.decode("utf-8"),
            parse_constant=_reject_json_constant,
            object_pairs_hook=_unique_json_object,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
        raise ValueError("seed must be one UTF-8 JSON document") from exc
    if not isinstance(payload, dict):
        raise TypeError("seed must be a JSON object")
    if set(payload) != {"setup", "steps"}:
        raise ValueError("seed must contain exactly setup and steps")

    setup = payload["setup"]
    if not isinstance(setup, list) or not all(isinstance(item, str) for item in setup):
        raise TypeError("setup must be a list of SQL strings")

    steps = payload["steps"]
    if not isinstance(steps, list):
        raise TypeError("steps must be a list")
    if not steps:
        raise ValueError("steps must be a non-empty list")

    for index, step in enumerate(steps):
        if not isinstance(step, dict):
            raise TypeError(f"step {index} must be a JSON object")
        connection = step.get("connection")
        if not isinstance(connection, str) or connection not in {"a", "b"}:
            raise ValueError(f"step {index} connection must be 'a' or 'b'")
        op = step.get("op")
        if not isinstance(op, str) or op not in _ALL_OPS:
            raise ValueError(f"step {index} op is unsupported")

        if op in _BEGIN_OPS:
            if set(step) != {"connection", "op", "mode"}:
                raise ValueError(
                    f"step {index} {op} must contain connection, op, and mode"
                )
            if step["mode"] not in _MODES:
                raise ValueError(
                    f"step {index} mode must be deferred, immediate, or exclusive"
                )
            continue

        if op in _SIMPLE_OPS:
            if set(step) != {"connection", "op"}:
                raise ValueError(f"step {index} {op} accepts only connection and op")
            continue

        if not {"connection", "op", "sql"} <= set(step):
            raise ValueError(f"step {index} {op} requires connection, op, and sql")
        if set(step) - {"connection", "op", "sql", "params"}:
            raise ValueError(f"step {index} {op} contains unknown fields")
        sql = step["sql"]
        if not isinstance(sql, str) or not sql.strip():
            raise ValueError(f"step {index} sql must be a non-empty string")
        _validate_params(step.get("params"), step_index=index)

    return payload


def _encode(payload: dict[str, Any]) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


class SQLiteTwoConnectionScenarioMutations:
    """Finite deterministic mutations for a valid two-connection SQLite scenario.

    Exact seed bytes are emitted first. Generated cases then walk ordered scenario
    steps. BEGIN/TRY_BEGIN modes probe the other supported lock-acquisition policies;
    SQL-operation parameter arrays receive bounded scalar replacements. SQL text,
    setup statements, step ordering, connection assignment, and operation kind remain
    unchanged. Duplicate and oversized candidates are skipped.
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
            steps = payload["steps"]
            assert isinstance(steps, list)

            for step_index, step in enumerate(steps):
                assert isinstance(step, dict)
                op = step["op"]
                if op not in _BEGIN_OPS:
                    continue
                mode = step["mode"]
                for replacement in _MODES:
                    if replacement == mode:
                        continue
                    candidate = dict(payload)
                    candidate_steps = [dict(item) for item in steps]
                    candidate_step = dict(step)
                    candidate_step["mode"] = replacement
                    candidate_steps[step_index] = candidate_step
                    candidate["steps"] = candidate_steps
                    encoded = _encode(candidate)
                    if len(encoded) > max_case_bytes or encoded in seen:
                        continue
                    cases.append(encoded)
                    seen.add(encoded)

            for step_index, step in enumerate(steps):
                assert isinstance(step, dict)
                if step["op"] not in _SQL_OPS:
                    continue
                params = _validate_params(step.get("params"), step_index=step_index)
                for param_index, value in enumerate(params):
                    for replacement in _mutation_values(value):
                        candidate = dict(payload)
                        candidate_steps = [dict(item) for item in steps]
                        candidate_step = dict(step)
                        candidate_params = list(params)
                        candidate_params[param_index] = replacement
                        candidate_step["params"] = candidate_params
                        candidate_steps[step_index] = candidate_step
                        candidate["steps"] = candidate_steps
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
