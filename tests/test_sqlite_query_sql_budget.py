from __future__ import annotations

import json

import pytest

from systems_conformance import DifferentialHarness
from systems_conformance.sqlite_adapter import SQLiteQueryTarget


def _request(*, setup: list[str], query: str) -> bytes:
    return json.dumps(
        {"setup": setup, "query": query, "params": []},
        separators=(",", ":"),
    ).encode()


def _execute(case: bytes, *, max_sql_bytes: int):
    return SQLiteQueryTarget(max_sql_bytes=max_sql_bytes).as_command_target().execute(
        case,
        timeout_seconds=2.0,
        max_output_bytes=4096,
        max_total_output_bytes=8192,
    )


def test_sqlite_query_sql_budget_allows_exact_utf8_byte_limit() -> None:
    result = _execute(_request(setup=[], query="SELECT 1"), max_sql_bytes=8)

    assert result.infrastructure_error is None
    assert result.exit_code == 0
    assert json.loads(result.stdout.text) == {"columns": ["1"], "rows": [[1]]}


def test_sqlite_query_sql_budget_rejects_oversized_query_before_execution() -> None:
    result = _execute(_request(setup=[], query="SELECT 1"), max_sql_bytes=7)

    assert result.infrastructure_error is None
    assert result.exit_code == 2
    assert result.stdout.text == ""
    assert result.stderr.text.strip() == "protocol_error: query exceeds max_sql_bytes: 7"


def test_sqlite_query_sql_budget_rejects_oversized_setup_statement() -> None:
    result = _execute(
        _request(setup=["SELECT 1"], query="SELECT 1"),
        max_sql_bytes=7,
    )

    assert result.infrastructure_error is None
    assert result.exit_code == 2
    assert result.stdout.text == ""
    assert result.stderr.text.strip() == (
        "protocol_error: setup statement exceeds max_sql_bytes: 7"
    )


@pytest.mark.parametrize("max_sql_bytes", [0, -1, True, 1.5, "8"])
def test_sqlite_query_target_rejects_invalid_sql_byte_budgets(max_sql_bytes: object) -> None:
    with pytest.raises(ValueError, match="max_sql_bytes must be a positive integer"):
        SQLiteQueryTarget(max_sql_bytes=max_sql_bytes)  # type: ignore[arg-type]


def test_sqlite_query_sql_budget_changes_replay_context() -> None:
    candidate = SQLiteQueryTarget(max_sql_bytes=7).as_command_target()
    oracle = SQLiteQueryTarget(max_sql_bytes=8).as_command_target()
    candidate_harness = DifferentialHarness(candidate=candidate, oracle=candidate)
    oracle_harness = DifferentialHarness(candidate=oracle, oracle=oracle)

    assert candidate_harness.replay_context_sha256 != oracle_harness.replay_context_sha256


def test_real_differential_harness_observes_sqlite_query_sql_budget() -> None:
    candidate = SQLiteQueryTarget(max_sql_bytes=7).as_command_target()
    oracle = SQLiteQueryTarget(max_sql_bytes=8).as_command_target()
    harness = DifferentialHarness(candidate=candidate, oracle=oracle, timeout_seconds=2.0)

    run = harness.evaluate(_request(setup=[], query="SELECT 1"))

    assert run.candidate.infrastructure_error is None
    assert run.oracle.infrastructure_error is None
    assert run.candidate.exit_code == 2
    assert run.candidate.stderr.text.strip() == "protocol_error: query exceeds max_sql_bytes: 7"
    assert run.oracle.exit_code == 0
    assert run.comparison.classification == "product_mismatch"
    assert run.signature is not None
    assert run.signature.kind == "product_mismatch"
