from __future__ import annotations

import json

import pytest

from systems_conformance import DifferentialHarness
from systems_conformance.sqlite_adapter import SQLiteQueryTarget


def _request(params: list[int]) -> bytes:
    placeholders = ",".join("?" for _ in params)
    return json.dumps(
        {"setup": [], "query": f"SELECT {placeholders}", "params": params},
        separators=(",", ":"),
    ).encode()


def _execute(params: list[int], *, max_params: int):
    return SQLiteQueryTarget(max_params=max_params).as_command_target().execute(
        _request(params),
        timeout_seconds=2.0,
        max_output_bytes=4096,
        max_total_output_bytes=8192,
    )


def test_sqlite_query_param_budget_allows_exact_boundary() -> None:
    result = _execute([1, 2], max_params=2)

    assert result.infrastructure_error is None
    assert result.exit_code == 0
    assert json.loads(result.stdout.text) == {"columns": ["?", "?"], "rows": [[1, 2]]}


def test_sqlite_query_param_budget_rejects_next_parameter_before_execution() -> None:
    result = _execute([1, 2], max_params=1)

    assert result.infrastructure_error is None
    assert result.exit_code == 2
    assert result.stdout.text == ""
    assert result.stderr.text.strip() == "protocol_error: params exceeds max_params: 1"


@pytest.mark.parametrize("max_params", [0, -1, True, 1.5, "10"])
def test_sqlite_query_target_rejects_invalid_param_budgets(max_params: object) -> None:
    with pytest.raises(ValueError, match="max_params must be a positive integer"):
        SQLiteQueryTarget(max_params=max_params)  # type: ignore[arg-type]


def test_sqlite_query_param_budget_changes_replay_context() -> None:
    candidate = SQLiteQueryTarget(max_params=1).as_command_target()
    oracle = SQLiteQueryTarget(max_params=2).as_command_target()
    candidate_harness = DifferentialHarness(candidate=candidate, oracle=candidate)
    oracle_harness = DifferentialHarness(candidate=oracle, oracle=oracle)

    assert candidate_harness.replay_context_sha256 != oracle_harness.replay_context_sha256


def test_real_differential_harness_observes_sqlite_query_param_budget() -> None:
    candidate = SQLiteQueryTarget(max_params=1).as_command_target()
    oracle = SQLiteQueryTarget(max_params=2).as_command_target()
    harness = DifferentialHarness(candidate=candidate, oracle=oracle, timeout_seconds=2.0)

    run = harness.evaluate(_request([1, 2]))

    assert run.candidate.infrastructure_error is None
    assert run.oracle.infrastructure_error is None
    assert run.candidate.exit_code == 2
    assert run.candidate.stderr.text.strip() == "protocol_error: params exceeds max_params: 1"
    assert run.oracle.exit_code == 0
    assert json.loads(run.oracle.stdout.text) == {"columns": ["?", "?"], "rows": [[1, 2]]}
    assert run.comparison.classification == "product_mismatch"
    assert run.signature is not None
    assert run.signature.kind == "product_mismatch"
