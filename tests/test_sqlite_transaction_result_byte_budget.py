from __future__ import annotations

import json

import pytest

from systems_conformance import DifferentialHarness, SQLiteTransactionTarget


def _request(transaction_sql: str, observe_sql: str = "SELECT 1") -> bytes:
    return json.dumps(
        {
            "setup": [],
            "transaction": [{"sql": transaction_sql, "params": []}],
            "observe": {"sql": observe_sql, "params": []},
        },
        separators=(",", ":"),
    ).encode()


def _execute(case: bytes, target: SQLiteTransactionTarget):
    return target.as_command_target().execute(
        case,
        timeout_seconds=2.0,
        max_output_bytes=4096,
        max_total_output_bytes=8192,
    )


@pytest.mark.parametrize("value", [0, -1, True, 1.5, "8"])
def test_transaction_target_rejects_invalid_result_byte_budgets(value: object) -> None:
    with pytest.raises(ValueError, match="max_result_bytes must be a positive integer"):
        SQLiteTransactionTarget(max_result_bytes=value)  # type: ignore[arg-type]


def test_transaction_result_byte_budget_counts_empty_rows_array() -> None:
    case = _request("SELECT 1 WHERE 0", "SELECT 1 WHERE 0")
    rejected = _execute(case, SQLiteTransactionTarget(max_result_bytes=1))
    accepted = _execute(case, SQLiteTransactionTarget(max_result_bytes=2))

    assert rejected.infrastructure_error is None
    assert rejected.exit_code == 4
    assert rejected.stderr.text.strip() == "result_error: result exceeds max_result_bytes: 1"
    assert accepted.infrastructure_error is None
    assert accepted.exit_code == 0
    transcript = json.loads(accepted.stdout.text)
    assert transcript["transaction"][0]["rows"] == []
    assert transcript["observation"]["rows"] == []


def test_transaction_result_byte_budget_accepts_exact_rows_json_boundary() -> None:
    result = _execute(
        _request("SELECT 1 UNION ALL SELECT 2"),
        SQLiteTransactionTarget(max_result_bytes=9),
    )

    assert result.infrastructure_error is None
    assert result.exit_code == 0
    assert json.loads(result.stdout.text)["transaction"][0]["rows"] == [[1], [2]]


def test_transaction_result_byte_budget_rejects_before_full_transcript_serialization() -> None:
    result = _execute(
        _request("SELECT 1 UNION ALL SELECT 2"),
        SQLiteTransactionTarget(max_result_bytes=8),
    )

    assert result.infrastructure_error is None
    assert result.exit_code == 4
    assert result.stdout.text == ""
    assert result.stderr.text.strip() == "result_error: result exceeds max_result_bytes: 8"


def test_transaction_result_byte_budget_is_part_of_replay_identity() -> None:
    low = SQLiteTransactionTarget(max_result_bytes=8).as_command_target()
    high = SQLiteTransactionTarget(max_result_bytes=9).as_command_target()

    assert low.argv != high.argv
    assert "--max-result-bytes" in low.argv


def test_real_harness_observes_transaction_result_byte_budget_as_product_mismatch() -> None:
    candidate = SQLiteTransactionTarget(max_result_bytes=8).as_command_target()
    oracle = SQLiteTransactionTarget(max_result_bytes=9).as_command_target()
    harness = DifferentialHarness(candidate=candidate, oracle=oracle, timeout_seconds=2.0)

    run = harness.evaluate(_request("SELECT 1 UNION ALL SELECT 2"))

    assert run.candidate.infrastructure_error is None
    assert run.oracle.infrastructure_error is None
    assert run.candidate.exit_code == 4
    assert run.oracle.exit_code == 0
    assert run.candidate.stderr.text.strip() == (
        "result_error: result exceeds max_result_bytes: 8"
    )
    assert json.loads(run.oracle.stdout.text)["transaction"][0]["rows"] == [[1], [2]]
    assert run.comparison.classification == "product_mismatch"
    assert run.signature is not None
    assert run.signature.kind == "product_mismatch"
