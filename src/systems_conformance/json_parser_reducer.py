from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

MAX_JSON_REDUCER_NESTING_DEPTH = 256


def _reject_constant(value: str) -> None:
    raise ValueError(f"non-standard JSON constant: {value}")


def _load(raw: bytes) -> Any:
    """Parse one strict UTF-8, standards-compliant JSON document or fail closed."""
    try:
        text = raw.decode("utf-8", errors="strict")
        return json.loads(text, parse_constant=_reject_constant)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("input is not strict JSON") from exc
    except RecursionError as exc:
        raise ValueError("JSON document exceeds parser recursion budget") from exc


def _validate_nesting_depth(value: Any) -> None:
    """Reject structures too deep for the recursive candidate walk before yielding."""
    stack: list[tuple[Any, int]] = [(value, 0)]
    while stack:
        current, depth = stack.pop()
        if depth > MAX_JSON_REDUCER_NESTING_DEPTH:
            raise ValueError(
                "JSON document exceeds reducer nesting depth "
                f"{MAX_JSON_REDUCER_NESTING_DEPTH}"
            )
        if isinstance(current, dict):
            stack.extend((item, depth + 1) for item in current.values())
        elif isinstance(current, list):
            stack.extend((item, depth + 1) for item in current)


def _encode(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("ascii")


def _local_reductions(value: Any) -> Iterator[Any]:
    if isinstance(value, dict):
        keys = sorted(value)
        for key in keys:
            reduced = dict(value)
            del reduced[key]
            yield reduced
        for key in keys:
            if key:
                reduced = dict(value)
                item = reduced.pop(key)
                if "" not in reduced:
                    reduced[""] = item
                    yield reduced
            for child in _local_reductions(value[key]):
                reduced = dict(value)
                reduced[key] = child
                yield reduced
    elif isinstance(value, list):
        for index in range(len(value)):
            yield value[:index] + value[index + 1 :]
        for index, item in enumerate(value):
            for child in _local_reductions(item):
                reduced = list(value)
                reduced[index] = child
                yield reduced
    elif isinstance(value, str):
        if value:
            yield ""
            if len(value) > 1:
                yield value[: len(value) // 2]
    elif isinstance(value, bool):
        if value:
            yield False
    elif isinstance(value, int):
        if value != 0:
            yield 0
    elif isinstance(value, float):
        if value != 0.0:
            yield 0


def json_reduction_candidates(raw: bytes) -> Iterator[bytes]:
    """Yield deterministic, unique, strictly smaller valid-JSON candidates.

    The reducer treats malformed UTF-8, malformed JSON, non-standard constants, and
    over-deep structures as infrastructure input errors rather than guessing at syntax.
    Candidates preserve a complete JSON document while deleting structure or shrinking
    semantic fields; the live failure predicate remains responsible for retaining only
    the target behavior.
    """
    value = _load(raw)
    _validate_nesting_depth(value)
    seen: set[bytes] = set()

    try:
        canonical = _encode(value)
        if len(canonical) < len(raw):
            seen.add(canonical)
            yield canonical

        for reduced in _local_reductions(value):
            candidate = _encode(reduced)
            if len(candidate) < len(raw) and candidate not in seen:
                seen.add(candidate)
                yield candidate
    except RecursionError as exc:
        raise ValueError("JSON reduction exceeded recursion budget") from exc
