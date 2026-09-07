from __future__ import annotations

import json

import pytest

from systems_conformance import DifferentialHarness
from systems_conformance.sqlite_transaction_adapter import SQLiteTransactionTarget


def _request(
    transaction_values: list[str], observe_values: list[str] | None = None
) -> bytes:
    transaction_placeholders = ", ".join("?" for _ in transaction_values)
    observe_values = [] if observe_values is None else observe_values
    observe_placeholders = ", ".join("?" for _ in observe_values)
    observe = (
        {"sql": "SELECT 1", "params": []}
        if not observe_values
        else {"sql": f"SELECT {observe_placeholders}", "params": observe_values}
    )
    return json.dumps(
        {
            "setup": [],
            "transaction": [
                {
                    "sql": f"SELECT {transaction_placeholders}",
                    "params": transaction_values,
                }
            ],
            "observe": observe,
        },
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")


def _execute(
    transaction_values: list[str],
    *,
    max_param_bytes: int,
    observe_values: list[str] | None = None,
):
    return SQLiteTransactionTarget(
        max_param_bytes=max_param_bytes
    ).as_command_target().execute(
        _request(transaction_values, observe_values),
        timeout_seconds=2.0,
        max_output_bytes=4096,
        max_total_output_bytes=8192,
    )


def test_sqlite_transaction_param_bytes_budget_allows_exact_utf8_boundary() -> None:
    result = _execute(["é", "é"], max_param_bytes=4)

    assert result.infrastructure_error is None
    assert result.exit_code == 0
    assert json.loads(result.stdout.text) == {
        "transaction": [{"columns": ["?", "?"], "rows": [["é", "é"]]}],
        "observation": {"columns": ["1"], "rows": [[1]]},
    }


def test_sqlite_transaction_param_bytes_budget_rejects_next_utf8_byte_before_execution() -> None:
    result = _execute(["é", "é"], max_param_bytes=3)

    assert result.infrastructure_error is None
    assert result.exit_code == 2
    assert result.stdout.text == ""
    assert result.stderr.text.strip() == (
        "protocol_error: transaction params exceed max_param_bytes: 3"
    )


def test_sqlite_transaction_param_bytes_budget_applies_to_observation() -> None:
    result = _execute(["ok"], max_param_bytes=3, observe_values=["é", "é"])

    assert result.infrastructure_error is None
    assert result.exit_code == 2
    assert result.stdout.text == ""
    assert result.stderr.text.strip() == (
        "protocol_error: observe params exceed max_param_bytes: 3"
    )


@pytest.mark.parametrize("max_param_bytes", [0, -1, True, 1.5, "10"])
def test_sqlite_transaction_target_rejects_invalid_param_byte_budgets(
    max_param_bytes: object,
) -> None:
    with pytest.raises(ValueError, match="max_param_bytes must be a positive integer"):
        SQLiteTransactionTarget(max_param_bytes=max_param_bytes)  # type: ignore[arg-type]


def test_sqlite_transaction_param_bytes_budget_changes_replay_context() -> None:
    candidate = SQLiteTransactionTarget(max_param_bytes=3).as_command_target()
    oracle = SQLiteTransactionTarget(max_param_bytes=4).as_command_target()
    candidate_harness = DifferentialHarness(candidate=candidate, oracle=candidate)
    oracle_harness = DifferentialHarness(candidate=oracle, oracle=oracle)

    assert candidate_harness.replay_context_sha256 != oracle_harness.replay_context_sha256


def test_real_differential_harness_observes_sqlite_transaction_param_bytes_budget() -> None:
    candidate = SQLiteTransactionTarget(max_param_bytes=3).as_command_target()
    oracle = SQLiteTransactionTarget(max_param_bytes=4).as_command_target()
    harness = DifferentialHarness(candidate=candidate, oracle=oracle, timeout_seconds=2.0)

    run = harness.evaluate(_request(["é", "é"]))

    assert run.candidate.infrastructure_error is None
    assert run.oracle.infrastructure_error is None
    assert run.candidate.exit_code == 2
    assert run.candidate.stderr.text.strip() == (
        "protocol_error: transaction params exceed max_param_bytes: 3"
    )
    assert run.oracle.exit_code == 0
    assert json.loads(run.oracle.stdout.text) == {
        "transaction": [{"columns": ["?", "?"], "rows": [["é", "é"]]}],
        "observation": {"columns": ["1"], "rows": [[1]]},
    }
    assert run.comparison.classification == "product_mismatch"
    assert run.signature is not None
    assert run.signature.kind == "product_mismatch"
