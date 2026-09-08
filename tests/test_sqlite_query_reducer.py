from __future__ import annotations

import json

import pytest

from systems_conformance import DifferentialHarness, SQLiteQueryTarget, reduce_case
from systems_conformance.sqlite_query_reducer import (
    sqlite_query_fault_occurrence_complexity,
    sqlite_query_fault_occurrence_reductions,
    sqlite_query_parameter_complexity,
    sqlite_query_parameter_reductions,
    sqlite_query_setup_statement_count,
    sqlite_query_setup_statement_deletions,
)


def _case(
    *,
    setup: list[str],
    query: str,
    params: list[object] | None = None,
    fault: dict[str, object] | None = None,
) -> bytes:
    payload: dict[str, object] = {
        "setup": setup,
        "query": query,
        "params": [] if params is None else params,
    }
    if fault is not None:
        payload["fault"] = fault
    return json.dumps(payload, separators=(",", ":")).encode()


def test_setup_statement_deletions_are_deterministic_and_strictly_smaller() -> None:
    case = _case(setup=["SELECT 1", "SELECT 2", "SELECT 3"], query="SELECT 4")
    first = list(sqlite_query_setup_statement_deletions(case))
    second = list(sqlite_query_setup_statement_deletions(case))

    assert first == second
    assert first
    assert all(sqlite_query_setup_statement_count(candidate) < 3 for candidate in first)
    assert all(json.loads(candidate)["query"] == "SELECT 4" for candidate in first)


def test_parameter_reductions_are_deterministic_and_strictly_simpler() -> None:
    case = _case(setup=[], query="SELECT ?, ?", params=[42, "value"])
    first = list(sqlite_query_parameter_reductions(case))
    second = list(sqlite_query_parameter_reductions(case))
    complexity = sqlite_query_parameter_complexity(case)

    assert first == second
    assert first
    assert all(sqlite_query_parameter_complexity(candidate) < complexity for candidate in first)
    assert json.loads(first[0])["params"] == [0, "value"]


def test_parameter_reducer_rejects_non_scalar_params() -> None:
    case = _case(setup=[], query="SELECT ?", params=[[1]])
    with pytest.raises(TypeError, match="JSON scalar"):
        sqlite_query_parameter_complexity(case)


def test_fault_occurrence_reductions_are_deterministic_and_strictly_lower() -> None:
    case = _case(
        setup=["SELECT 1"],
        query="SELECT 2",
        fault={"operation": "setup", "occurrence": 9, "kind": "abort"},
    )
    first = list(sqlite_query_fault_occurrence_reductions(case))
    second = list(sqlite_query_fault_occurrence_reductions(case))

    assert first == second
    assert [json.loads(candidate)["fault"]["occurrence"] for candidate in first] == [0, 1, 2]
    assert all(sqlite_query_fault_occurrence_complexity(candidate) < 9 for candidate in first)


def test_real_row_budget_failure_reduces_to_required_setup() -> None:
    candidate = SQLiteQueryTarget(max_result_rows=1).as_command_target()
    oracle = SQLiteQueryTarget(max_result_rows=2).as_command_target()
    harness = DifferentialHarness(candidate=candidate, oracle=oracle, timeout_seconds=2.0)
    initial = _case(
        setup=[
            "CREATE TABLE items(v INTEGER)",
            "CREATE TABLE noise(v INTEGER)",
            "INSERT INTO items VALUES (1)",
            "INSERT INTO items VALUES (2)",
        ],
        query="SELECT v FROM items ORDER BY v",
    )
    initial_run = harness.evaluate(initial)
    assert initial_run.signature is not None
    signature = initial_run.signature

    reduction = reduce_case(
        initial,
        candidates=sqlite_query_setup_statement_deletions,
        preserves_failure=lambda case: harness.preserves_failure(case, signature),
        measure=sqlite_query_setup_statement_count,
        max_evaluations=64,
    )
    reduced = json.loads(reduction.reduced)
    rerun = harness.evaluate(reduction.reduced)

    assert rerun.signature == signature
    assert rerun.comparison.classification == "product_mismatch"
    assert reduced["setup"] == [
        "CREATE TABLE items(v INTEGER)",
        "INSERT INTO items VALUES (1)",
        "INSERT INTO items VALUES (2)",
    ]
    assert reduction.accepted_steps > 0


def test_real_fault_failure_reduces_query_scalar() -> None:
    candidate = SQLiteQueryTarget(enable_faults=True).as_command_target()
    oracle = SQLiteQueryTarget(enable_faults=False).as_command_target()
    harness = DifferentialHarness(candidate=candidate, oracle=oracle, timeout_seconds=2.0)
    initial = _case(
        setup=[],
        query="SELECT ?",
        params=[987654],
        fault={"operation": "query", "occurrence": 0, "kind": "abort"},
    )
    initial_run = harness.evaluate(initial)
    assert initial_run.signature is not None
    signature = initial_run.signature

    reduction = reduce_case(
        initial,
        candidates=sqlite_query_parameter_reductions,
        preserves_failure=lambda case: harness.preserves_failure(case, signature),
        measure=sqlite_query_parameter_complexity,
        max_evaluations=16,
    )
    reduced = json.loads(reduction.reduced)
    rerun = harness.evaluate(reduction.reduced)

    assert rerun.signature == signature
    assert reduced["params"] == [None]
    assert sqlite_query_parameter_complexity(reduction.reduced) == 0
    assert reduction.accepted_steps > 0


def test_real_fault_failure_reduces_occurrence_and_preserves_signature() -> None:
    candidate = SQLiteQueryTarget(enable_faults=True).as_command_target()
    oracle = SQLiteQueryTarget(enable_faults=False).as_command_target()
    harness = DifferentialHarness(candidate=candidate, oracle=oracle, timeout_seconds=2.0)
    initial = _case(
        setup=["SELECT 1", "SELECT 2", "SELECT 3"],
        query="SELECT 4",
        fault={"operation": "setup", "occurrence": 2, "kind": "abort"},
    )
    initial_run = harness.evaluate(initial)
    assert initial_run.signature is not None
    signature = initial_run.signature

    reduction = reduce_case(
        initial,
        candidates=sqlite_query_fault_occurrence_reductions,
        preserves_failure=lambda case: harness.preserves_failure(case, signature),
        measure=sqlite_query_fault_occurrence_complexity,
        max_evaluations=8,
    )
    reduced = json.loads(reduction.reduced)
    rerun = harness.evaluate(reduction.reduced)

    assert rerun.signature == signature
    assert reduced["fault"] == {"operation": "setup", "occurrence": 0, "kind": "abort"}
    assert sqlite_query_fault_occurrence_complexity(reduction.reduced) == 0
    assert reduction.accepted_steps > 0
