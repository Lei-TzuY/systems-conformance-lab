from __future__ import annotations

import json

import pytest

from systems_conformance.sqlite_two_connection_reducer import (
    sqlite_two_connection_parameter_complexity,
    sqlite_two_connection_parameter_reductions,
    sqlite_two_connection_setup_count,
    sqlite_two_connection_setup_deletions,
    sqlite_two_connection_step_count,
    sqlite_two_connection_step_deletions,
)


def _case(*, setup: list[str], steps: list[dict[str, object]]) -> bytes:
    return json.dumps(
        {"setup": setup, "steps": steps},
        separators=(",", ":"),
    ).encode()


def test_step_deletions_are_deterministic_and_keep_one_step() -> None:
    case = _case(
        setup=["CREATE TABLE items(v INTEGER)"],
        steps=[
            {"connection": "a", "op": "query", "sql": "SELECT 1"},
            {"connection": "b", "op": "query", "sql": "SELECT 2"},
            {"connection": "a", "op": "query", "sql": "SELECT 3"},
        ],
    )

    first = list(sqlite_two_connection_step_deletions(case))
    second = list(sqlite_two_connection_step_deletions(case))

    assert first == second
    assert first
    assert all(sqlite_two_connection_step_count(candidate) < 3 for candidate in first)
    assert all(json.loads(candidate)["steps"] for candidate in first)
    assert all(
        json.loads(candidate)["setup"] == ["CREATE TABLE items(v INTEGER)"]
        for candidate in first
    )


def test_setup_deletions_are_deterministic_and_may_reduce_to_empty() -> None:
    case = _case(
        setup=[
            "CREATE TABLE items(v INTEGER)",
            "CREATE TABLE noise(v INTEGER)",
        ],
        steps=[{"connection": "a", "op": "query", "sql": "SELECT v FROM items"}],
    )

    first = list(sqlite_two_connection_setup_deletions(case))
    second = list(sqlite_two_connection_setup_deletions(case))

    assert first == second
    assert first
    assert all(sqlite_two_connection_setup_count(candidate) < 2 for candidate in first)
    assert any(json.loads(candidate)["setup"] == [] for candidate in first)
    assert all(len(json.loads(candidate)["steps"]) == 1 for candidate in first)


def test_parameter_reductions_cover_step_params_and_are_strictly_simpler() -> None:
    case = _case(
        setup=["CREATE TABLE items(v INTEGER)"],
        steps=[
            {
                "connection": "a",
                "op": "query",
                "sql": "SELECT v FROM items WHERE v >= ?",
                "params": [987654],
            },
            {
                "connection": "b",
                "op": "try_execute",
                "sql": "INSERT INTO items VALUES (?)",
                "params": ["payload"],
            },
        ],
    )

    first = list(sqlite_two_connection_parameter_reductions(case))
    second = list(sqlite_two_connection_parameter_reductions(case))
    original = sqlite_two_connection_parameter_complexity(case)

    assert first == second
    assert first
    assert all(
        sqlite_two_connection_parameter_complexity(candidate) < original for candidate in first
    )
    decoded = [json.loads(candidate) for candidate in first]
    assert decoded[0]["steps"][0]["params"] == [0]
    assert any(candidate["steps"][1]["params"] == [""] for candidate in decoded)
    assert all(candidate["setup"] == ["CREATE TABLE items(v INTEGER)"] for candidate in decoded)


@pytest.mark.parametrize(
    ("case", "message"),
    [
        (b'{"setup":[],"steps":[]}', "steps must be a non-empty list"),
        (
            (
                b'{"setup":[],"steps":[{"connection":"a","op":"query","sql":"SELECT 1"}],'
                b'"steps":[{"connection":"b","op":"query","sql":"SELECT 2"}]}'
            ),
            "duplicate JSON object field: steps",
        ),
    ],
)
def test_reducer_rejects_invalid_structural_shape(case: bytes, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        sqlite_two_connection_step_count(case)


def test_parameter_reducer_rejects_non_scalar_params() -> None:
    case = _case(
        setup=[],
        steps=[
            {
                "connection": "a",
                "op": "query",
                "sql": "SELECT ?",
                "params": [[1]],
            }
        ],
    )

    with pytest.raises(TypeError, match="JSON scalar"):
        sqlite_two_connection_parameter_complexity(case)
