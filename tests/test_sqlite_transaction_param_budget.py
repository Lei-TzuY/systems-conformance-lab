from __future__ import annotations

import json

import pytest

from systems_conformance import DifferentialHarness
from systems_conformance.sqlite_transaction_adapter import SQLiteTransactionTarget


def _request(transaction_params: list[int], observe_params: list[int] | None = None) -> bytes:
    transaction_placeholders = ",".join("?" for _ in transaction_params)
    observe_params = [] if observe_params is None else observe_params
    observe_placeholders = ",".join("?" for _ in observe_params)
    observe_sql = "SELECT 1" if not observe_params else f"SELECT {observe_placeholders}"
    return json.dumps(
        {
            "setup": [],
            "transaction": [
                {
                    "sql": f"SELECT {transaction_placeholders}",
                    "params": transaction_params,
                }
            ],
            "observe": {"sql": observe_sql, "params": observe_params},
        },
        separators=(",", ":"),
    ).encode()


def _execute(
    transaction_params: list[int],
    *,
    max_params: int,
    observe_params: list[int] | None = None,
):
    return SQLiteTransactionTarget(max_params=max_params).as_command_target().execute(
        _request(transaction_params, observe_params),
        timeout_seconds=2.0,
        max_output_bytes=4096,
        max_total_output_bytes=8192,
    )


def test_sqlite_transaction_param_budget_allows_exact_boundary() -> None:
    result = _execute([1, 2], max_params=2)

    assert result.infrastructure_error is None
    assert result.exit_code == 0
    assert json.loads(result.stdout.text) == {
        "transaction": [{"columns": ["?", "?"], "rows": [[1, 2]]}],
        "observation": {"columns": ["1"], "rows": [[1]]},
    }


def test_sqlite_transaction_param_budget_rejects_next_parameter_before_execution() -> None:
    result = _execute([1, 2], max_params=1)

    assert result.infrastructure_error is None
    assert result.exit_code == 2
    assert result.stdout.text == ""
    assert (
        result.stderr.text.strip()
        == "protocol_error: transaction params exceeds max_params: 1"
    )


def test_sqlite_transaction_param_budget_applies_to_observation() -> None:
    result = _execute([1], max_params=1, observe_params=[2, 3])

    assert result.infrastructure_error is None
    assert result.exit_code == 2
    assert result.stdout.text == ""
    assert result.stderr.text.strip() == "protocol_error: observe params exceeds max_params: 1"


@pytest.mark.parametrize("max_params", [0, -1, True, 1.5, "10"])
def test_sqlite_transaction_target_rejects_invalid_param_budgets(max_params: object) -> None:
    with pytest.raises(ValueError, match="max_params must be a positive integer"):
        SQLiteTransactionTarget(max_params=max_params)  # type: ignore[arg-type]


def test_sqlite_transaction_param_budget_changes_replay_context() -> None:
    candidate = SQLiteTransactionTarget(max_params=1).as_command_target()
    oracle = SQLiteTransactionTarget(max_params=2).as_command_target()
    candidate_harness = DifferentialHarness(candidate=candidate, oracle=candidate)
    oracle_harness = DifferentialHarness(candidate=oracle, oracle=oracle)

    assert candidate_harness.replay_context_sha256 != oracle_harness.replay_context_sha256


def test_real_differential_harness_observes_sqlite_transaction_param_budget() -> None:
    candidate = SQLiteTransactionTarget(max_params=1).as_command_target()
    oracle = SQLiteTransactionTarget(max_params=2).as_command_target()
    harness = DifferentialHarness(candidate=candidate, oracle=oracle, timeout_seconds=2.0)

    run = harness.evaluate(_request([1, 2]))

    assert run.candidate.infrastructure_error is None
    assert run.oracle.infrastructure_error is None
    assert run.candidate.exit_code == 2
    assert (
        run.candidate.stderr.text.strip()
        == "protocol_error: transaction params exceeds max_params: 1"
    )
    assert run.oracle.exit_code == 0
    assert json.loads(run.oracle.stdout.text) == {
        "transaction": [{"columns": ["?", "?"], "rows": [[1, 2]]}],
        "observation": {"columns": ["1"], "rows": [[1]]},
    }
    assert run.comparison.classification == "product_mismatch"
    assert run.signature is not None
    assert run.signature.kind == "product_mismatch"
