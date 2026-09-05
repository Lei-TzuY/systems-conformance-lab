from __future__ import annotations

import json
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
        raise ValueError("case must be a JSON object")

    setup = payload.get("setup", [])
    transaction = payload.get("transaction")
    if not isinstance(setup, list):
        raise ValueError("setup must be a list")
    if not isinstance(transaction, list) or not transaction:
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
