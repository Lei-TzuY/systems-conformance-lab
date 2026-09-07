from __future__ import annotations

import json

import pytest

from systems_conformance import DifferentialHarness
from systems_conformance.sqlite_adapter import SQLiteQueryTarget


def _request(query: str) -> bytes:
    return json.dumps(
        {"setup": [], "query": query, "params": []},
        separators=(",", ":"),
    ).encode()


def _execute(query: str, *, max_result_columns: int):
    return SQLiteQueryTarget(
        max_result_columns=max_result_columns
    ).as_command_target().execute(
        _request(query),
        timeout_seconds=2.0,
        max_output_bytes=4096,
        max_total_output_bytes=8192,
    )


def test_sqlite_query_result_column_budget_allows_exact_boundary() -> None:
    result = _execute("SELECT 1 AS a, 2 AS b, 3 AS c", max_result_columns=3)

    assert result.infrastructure_error is None
    assert result.exit_code == 0
    assert json.loads(result.stdout.text) == {
        "columns": ["a", "b", "c"],
        "rows": [[1, 2, 3]],
    }


def test_sqlite_query_result_column_budget_rejects_next_column_before_rows() -> None:
    result = _execute("SELECT 1 AS a, 2 AS b, 3 AS c", max_result_columns=2)

    assert result.infrastructure_error is None
    assert result.exit_code == 4
    assert result.stdout.text == ""
    assert result.stderr.text.strip() == "result_error: result exceeds max_result_columns: 2"


@pytest.mark.parametrize("max_result_columns", [0, -1, True, 1.5, "10"])
def test_sqlite_query_target_rejects_invalid_result_column_budgets(
    max_result_columns: object,
) -> None:
    with pytest.raises(ValueError, match="max_result_columns must be a positive integer"):
        SQLiteQueryTarget(max_result_columns=max_result_columns)  # type: ignore[arg-type]


def test_sqlite_query_result_column_budget_changes_replay_context() -> None:
    candidate = SQLiteQueryTarget(max_result_columns=2).as_command_target()
    oracle = SQLiteQueryTarget(max_result_columns=3).as_command_target()
    candidate_harness = DifferentialHarness(candidate=candidate, oracle=candidate)
    oracle_harness = DifferentialHarness(candidate=oracle, oracle=oracle)

    assert candidate_harness.replay_context_sha256 != oracle_harness.replay_context_sha256


def test_real_differential_harness_observes_sqlite_query_result_column_budget() -> None:
    candidate = SQLiteQueryTarget(max_result_columns=2).as_command_target()
    oracle = SQLiteQueryTarget(max_result_columns=3).as_command_target()
    harness = DifferentialHarness(candidate=candidate, oracle=oracle, timeout_seconds=2.0)

    run = harness.evaluate(_request("SELECT 1 AS a, 2 AS b, 3 AS c"))

    assert run.candidate.infrastructure_error is None
    assert run.oracle.infrastructure_error is None
    assert run.candidate.exit_code == 4
    assert run.candidate.stderr.text.strip() == (
        "result_error: result exceeds max_result_columns: 2"
    )
    assert run.oracle.exit_code == 0
    assert json.loads(run.oracle.stdout.text)["columns"] == ["a", "b", "c"]
    assert run.comparison.classification == "product_mismatch"
    assert run.signature is not None
    assert run.signature.kind == "product_mismatch"
