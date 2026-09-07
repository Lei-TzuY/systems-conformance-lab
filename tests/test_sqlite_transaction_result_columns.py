from __future__ import annotations

import json

import pytest

from systems_conformance import DifferentialHarness, SQLiteTransactionTarget


def _statement(sql: str) -> dict[str, object]:
    return {"sql": sql, "params": []}


def _request(*, transaction_sql: str, observe_sql: str = "SELECT 1 AS observed") -> bytes:
    return json.dumps(
        {
            "setup": [],
            "transaction": [_statement(transaction_sql)],
            "observe": _statement(observe_sql),
        },
        separators=(",", ":"),
    ).encode()


def _execute(case: bytes, *, max_result_columns: int):
    return SQLiteTransactionTarget(
        max_result_columns=max_result_columns
    ).as_command_target().execute(
        case,
        timeout_seconds=2.0,
        max_output_bytes=4096,
        max_total_output_bytes=8192,
    )


def test_transaction_result_column_budget_allows_exact_boundary() -> None:
    result = _execute(
        _request(transaction_sql="SELECT 1 AS a, 2 AS b, 3 AS c"),
        max_result_columns=3,
    )

    assert result.infrastructure_error is None
    assert result.exit_code == 0
    payload = json.loads(result.stdout.text)
    assert payload["transaction"][0] == {
        "columns": ["a", "b", "c"],
        "rows": [[1, 2, 3]],
    }


def test_transaction_result_column_budget_rejects_next_column_before_rows() -> None:
    result = _execute(
        _request(transaction_sql="SELECT 1 AS a, 2 AS b, 3 AS c"),
        max_result_columns=2,
    )

    assert result.infrastructure_error is None
    assert result.exit_code == 4
    assert result.stdout.text == ""
    assert result.stderr.text.strip() == "result_error: result exceeds max_result_columns: 2"


def test_transaction_result_column_budget_applies_to_observation() -> None:
    result = _execute(
        _request(
            transaction_sql="SELECT 1 AS transaction_value",
            observe_sql="SELECT 1 AS a, 2 AS b, 3 AS c",
        ),
        max_result_columns=2,
    )

    assert result.infrastructure_error is None
    assert result.exit_code == 4
    assert result.stdout.text == ""
    assert result.stderr.text.strip() == "result_error: result exceeds max_result_columns: 2"


@pytest.mark.parametrize("max_result_columns", [0, -1, True, 1.5, "10"])
def test_transaction_target_rejects_invalid_result_column_budgets(
    max_result_columns: object,
) -> None:
    with pytest.raises(ValueError, match="max_result_columns must be a positive integer"):
        SQLiteTransactionTarget(max_result_columns=max_result_columns)  # type: ignore[arg-type]


def test_transaction_result_column_budget_changes_replay_context() -> None:
    candidate = SQLiteTransactionTarget(max_result_columns=2).as_command_target()
    oracle = SQLiteTransactionTarget(max_result_columns=3).as_command_target()
    candidate_harness = DifferentialHarness(candidate=candidate, oracle=candidate)
    oracle_harness = DifferentialHarness(candidate=oracle, oracle=oracle)

    assert candidate_harness.replay_context_sha256 != oracle_harness.replay_context_sha256


def test_real_differential_harness_observes_transaction_result_column_budget() -> None:
    candidate = SQLiteTransactionTarget(max_result_columns=2).as_command_target()
    oracle = SQLiteTransactionTarget(max_result_columns=3).as_command_target()
    harness = DifferentialHarness(candidate=candidate, oracle=oracle, timeout_seconds=2.0)

    run = harness.evaluate(_request(transaction_sql="SELECT 1 AS a, 2 AS b, 3 AS c"))

    assert run.candidate.infrastructure_error is None
    assert run.oracle.infrastructure_error is None
    assert run.candidate.exit_code == 4
    assert run.candidate.stderr.text.strip() == (
        "result_error: result exceeds max_result_columns: 2"
    )
    assert run.oracle.exit_code == 0
    assert json.loads(run.oracle.stdout.text)["transaction"][0]["columns"] == [
        "a",
        "b",
        "c",
    ]
    assert run.comparison.classification == "product_mismatch"
    assert run.signature is not None
    assert run.signature.kind == "product_mismatch"
