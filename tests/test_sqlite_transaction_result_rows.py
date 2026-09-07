from __future__ import annotations

import json

import pytest

from systems_conformance import DifferentialHarness, SQLiteTransactionTarget


def _request() -> bytes:
    return json.dumps(
        {
            "setup": [],
            "transaction": [
                {
                    "sql": (
                        "WITH RECURSIVE t(x) AS (VALUES(1) UNION ALL "
                        "SELECT x+1 FROM t WHERE x<3) SELECT x FROM t"
                    ),
                    "params": [],
                }
            ],
            "observe": {"sql": "SELECT 1", "params": []},
        },
        separators=(",", ":"),
    ).encode()


def _execute(max_result_rows: int):
    return SQLiteTransactionTarget(max_result_rows=max_result_rows).as_command_target().execute(
        _request(),
        timeout_seconds=2.0,
        max_output_bytes=4096,
        max_total_output_bytes=8192,
    )


def test_transaction_result_row_budget_accepts_exact_boundary() -> None:
    result = _execute(3)

    assert result.infrastructure_error is None
    assert result.exit_code == 0
    assert result.stderr.text == ""
    assert json.loads(result.stdout.text)["transaction"][0]["rows"] == [[1], [2], [3]]


def test_transaction_result_row_budget_rejects_first_excess_row() -> None:
    result = _execute(2)

    assert result.infrastructure_error is None
    assert result.exit_code == 4
    assert result.stdout.text == ""
    assert result.stderr.text.strip() == "result_error: result exceeds max_result_rows: 2"


@pytest.mark.parametrize("value", [0, -1, True])
def test_transaction_result_row_budget_rejects_invalid_configuration(value: object) -> None:
    with pytest.raises(ValueError, match="max_result_rows must be a positive integer"):
        SQLiteTransactionTarget(max_result_rows=value)  # type: ignore[arg-type]


def test_transaction_result_row_budget_is_part_of_target_identity() -> None:
    smaller = SQLiteTransactionTarget(max_result_rows=2).as_command_target()
    larger = SQLiteTransactionTarget(max_result_rows=3).as_command_target()

    assert smaller.argv != larger.argv
    assert "--max-result-rows" in smaller.argv


def test_real_harness_classifies_result_row_budget_difference_as_product_mismatch() -> None:
    harness = DifferentialHarness(
        candidate=SQLiteTransactionTarget(max_result_rows=2).as_command_target(),
        oracle=SQLiteTransactionTarget(max_result_rows=3).as_command_target(),
        timeout_seconds=2.0,
    )

    run = harness.evaluate(_request())

    assert run.candidate.infrastructure_error is None
    assert run.oracle.infrastructure_error is None
    assert run.candidate.exit_code == 4
    assert run.oracle.exit_code == 0
    assert run.candidate.stderr.text.strip() == (
        "result_error: result exceeds max_result_rows: 2"
    )
    assert json.loads(run.oracle.stdout.text)["transaction"][0]["rows"] == [[1], [2], [3]]
    assert run.comparison.classification == "product_mismatch"
    assert run.signature is not None
    assert run.signature.kind == "product_mismatch"
