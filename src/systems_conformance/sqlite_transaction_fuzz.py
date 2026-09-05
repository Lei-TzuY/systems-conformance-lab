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

    transaction = payload.get("transaction")
    if not isinstance(transaction, list) or not transaction:
        raise ValueError("transaction must be a non-empty list")
    for statement in transaction:
        if not isinstance(statement, dict):
            raise TypeError("transaction statements must be JSON objects")
        params = statement.get("params", [])
        if not isinstance(params, list):
            raise TypeError("transaction statement params must be a JSON array")
        for value in params:
            _mutation_values(value)
    return payload


def _mutation_values(value: Any) -> tuple[Any, ...]:
    if value is None:
        return (0, "")
    if isinstance(value, bool):
        return (not value,)
    if isinstance(value, int):
        if not -(1 << 63) <= value < (1 << 63):
            raise ValueError("integer params must fit signed 64-bit SQLite range")
        return tuple(candidate for candidate in (0, 1, -1) if candidate != value)
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("floating params must be finite")
        return tuple(candidate for candidate in (0.0, 1.0, -1.0) if candidate != value)
    if isinstance(value, str):
        return tuple(candidate for candidate in ("", "0", "x") if candidate != value)
    raise TypeError("transaction params may only contain JSON scalar values")


def _encode(payload: dict[str, Any]) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


class SQLiteTransactionParameterMutations:
    """Finite deterministic corpus for SQLite transaction scalar parameters.

    Exact seed bytes are emitted first. Mutations then walk seeds, transaction
    statements, parameters, and a small type-aware replacement schedule in that
    order. JSON structure and all non-parameter fields are preserved, so the
    SQLite worker receives syntactically valid protocol shapes rather than random
    byte damage. Duplicate and oversized generated cases are skipped.
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
            transaction = payload["transaction"]
            assert isinstance(transaction, list)
            for statement_index, statement in enumerate(transaction):
                assert isinstance(statement, dict)
                params = statement.get("params", [])
                assert isinstance(params, list)
                for param_index, value in enumerate(params):
                    for replacement in _mutation_values(value):
                        candidate = dict(payload)
                        candidate_transaction = [dict(item) for item in transaction]
                        candidate_statement = candidate_transaction[statement_index]
                        candidate_params = list(params)
                        candidate_params[param_index] = replacement
                        candidate_statement["params"] = candidate_params
                        candidate["transaction"] = candidate_transaction
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
