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


def _execute(query: str, *, max_result_rows: int):
    return SQLiteQueryTarget(max_result_rows=max_result_rows).as_command_target().execute(
        _request(query),
        timeout_seconds=2.0,
        max_output_bytes=4096,
        max_total_output_bytes=8192,
    )


def test_sqlite_query_result_row_budget_allows_exact_boundary() -> None:
    result = _execute(
        "WITH RECURSIVE n(x) AS (VALUES(1) UNION ALL SELECT x+1 FROM n WHERE x<3) SELECT x FROM n",
        max_result_rows=3,
    )

    assert result.infrastructure_error is None
    assert result.exit_code == 0
    assert json.loads(result.stdout.text) == {
        "columns": ["x"],
        "rows": [[1], [2], [3]],
    }


def test_sqlite_query_result_row_budget_rejects_next_row_deterministically() -> None:
    result = _execute(
        "WITH RECURSIVE n(x) AS (VALUES(1) UNION ALL SELECT x+1 FROM n WHERE x<4) SELECT x FROM n",
        max_result_rows=3,
    )

    assert result.infrastructure_error is None
    assert result.exit_code == 4
    assert result.stdout.text == ""
    assert result.stderr.text.strip() == "result_error: result exceeds max_result_rows: 3"


@pytest.mark.parametrize("max_result_rows", [0, -1, True, 1.5, "10"])
def test_sqlite_query_target_rejects_invalid_result_row_budgets(max_result_rows: object) -> None:
    with pytest.raises(ValueError, match="max_result_rows must be a positive integer"):
        SQLiteQueryTarget(max_result_rows=max_result_rows)  # type: ignore[arg-type]


def test_sqlite_query_result_row_budget_changes_replay_context() -> None:
    candidate = SQLiteQueryTarget(max_result_rows=2).as_command_target()
    oracle = SQLiteQueryTarget(max_result_rows=3).as_command_target()
    candidate_harness = DifferentialHarness(candidate=candidate, oracle=candidate)
    oracle_harness = DifferentialHarness(candidate=oracle, oracle=oracle)

    assert candidate_harness.replay_context_sha256 != oracle_harness.replay_context_sha256


def test_real_differential_harness_observes_sqlite_query_result_row_budget() -> None:
    candidate = SQLiteQueryTarget(max_result_rows=2).as_command_target()
    oracle = SQLiteQueryTarget(max_result_rows=3).as_command_target()
    harness = DifferentialHarness(candidate=candidate, oracle=oracle, timeout_seconds=2.0)
    case = _request(
        "WITH RECURSIVE n(x) AS (VALUES(1) UNION ALL SELECT x+1 FROM n WHERE x<3) SELECT x FROM n"
    )

    run = harness.evaluate(case)

    assert run.candidate.infrastructure_error is None
    assert run.oracle.infrastructure_error is None
    assert run.candidate.exit_code == 4
    assert run.candidate.stderr.text.strip() == "result_error: result exceeds max_result_rows: 2"
    assert run.oracle.exit_code == 0
    assert run.comparison.classification == "product_mismatch"
    assert run.signature is not None
    assert run.signature.kind == "product_mismatch"
