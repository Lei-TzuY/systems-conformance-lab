from __future__ import annotations

import json

import pytest

from systems_conformance import DifferentialHarness
from systems_conformance.sqlite_adapter import SQLiteQueryTarget


def _request(setup: list[str]) -> bytes:
    return json.dumps(
        {"setup": setup, "query": "SELECT count(*) AS n FROM t", "params": []},
        separators=(",", ":"),
    ).encode()


def _execute(setup: list[str], *, max_setup_statements: int):
    return SQLiteQueryTarget(
        max_setup_statements=max_setup_statements
    ).as_command_target().execute(
        _request(setup),
        timeout_seconds=2.0,
        max_output_bytes=4096,
        max_total_output_bytes=8192,
    )


def test_sqlite_query_setup_statement_budget_allows_exact_boundary() -> None:
    setup = ["CREATE TABLE t(x INTEGER)", "INSERT INTO t VALUES (1)"]
    result = _execute(setup, max_setup_statements=2)

    assert result.infrastructure_error is None
    assert result.exit_code == 0
    assert json.loads(result.stdout.text) == {"columns": ["n"], "rows": [[1]]}


def test_sqlite_query_setup_statement_budget_rejects_next_statement_before_execution() -> None:
    setup = ["CREATE TABLE t(x INTEGER)", "INSERT INTO t VALUES (1)"]
    result = _execute(setup, max_setup_statements=1)

    assert result.infrastructure_error is None
    assert result.exit_code == 2
    assert result.stdout.text == ""
    assert result.stderr.text.strip() == (
        "protocol_error: setup exceeds max_setup_statements: 1"
    )


@pytest.mark.parametrize("max_setup_statements", [0, -1, True, 1.5, "10"])
def test_sqlite_query_target_rejects_invalid_setup_statement_budgets(
    max_setup_statements: object,
) -> None:
    with pytest.raises(ValueError, match="max_setup_statements must be a positive integer"):
        SQLiteQueryTarget(max_setup_statements=max_setup_statements)  # type: ignore[arg-type]


def test_sqlite_query_setup_statement_budget_changes_replay_context() -> None:
    candidate = SQLiteQueryTarget(max_setup_statements=1).as_command_target()
    oracle = SQLiteQueryTarget(max_setup_statements=2).as_command_target()
    candidate_harness = DifferentialHarness(candidate=candidate, oracle=candidate)
    oracle_harness = DifferentialHarness(candidate=oracle, oracle=oracle)

    assert candidate_harness.replay_context_sha256 != oracle_harness.replay_context_sha256


def test_real_differential_harness_observes_sqlite_query_setup_statement_budget() -> None:
    candidate = SQLiteQueryTarget(max_setup_statements=1).as_command_target()
    oracle = SQLiteQueryTarget(max_setup_statements=2).as_command_target()
    harness = DifferentialHarness(candidate=candidate, oracle=oracle, timeout_seconds=2.0)
    setup = ["CREATE TABLE t(x INTEGER)", "INSERT INTO t VALUES (1)"]

    run = harness.evaluate(_request(setup))

    assert run.candidate.infrastructure_error is None
    assert run.oracle.infrastructure_error is None
    assert run.candidate.exit_code == 2
    assert run.candidate.stderr.text.strip() == (
        "protocol_error: setup exceeds max_setup_statements: 1"
    )
    assert run.oracle.exit_code == 0
    assert json.loads(run.oracle.stdout.text) == {"columns": ["n"], "rows": [[1]]}
    assert run.comparison.classification == "product_mismatch"
    assert run.signature is not None
    assert run.signature.kind == "product_mismatch"
