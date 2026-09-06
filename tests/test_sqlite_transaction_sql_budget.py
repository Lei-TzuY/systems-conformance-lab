from __future__ import annotations

import json

import pytest

from systems_conformance import DifferentialHarness, SQLiteTransactionTarget


def _request(*, setup: list[str], transaction_sql: str, observe_sql: str) -> bytes:
    return json.dumps(
        {
            "setup": setup,
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


@pytest.mark.parametrize("max_sql_bytes", [0, -1, True])
def test_transaction_target_rejects_invalid_sql_byte_budget(max_sql_bytes: int) -> None:
    with pytest.raises(ValueError, match="max_sql_bytes must be a positive integer"):
        SQLiteTransactionTarget(max_sql_bytes=max_sql_bytes)


def test_transaction_target_accepts_sql_exactly_at_byte_budget() -> None:
    sql = "SELECT 1"
    assert len(sql.encode("utf-8")) == 8
    result = _execute(
        _request(setup=[], transaction_sql=sql, observe_sql=sql),
        SQLiteTransactionTarget(max_sql_bytes=8),
    )

    assert result.infrastructure_error is None
    assert result.exit_code == 0
    assert json.loads(result.stdout.text) == {
        "transaction": [{"columns": ["1"], "rows": [[1]]}],
        "observation": {"columns": ["1"], "rows": [[1]]},
    }


@pytest.mark.parametrize(
    ("setup", "transaction_sql", "observe_sql", "field"),
    [
        (["SELECT 1 "], "SELECT 1", "SELECT 1", "setup"),
        ([], "SELECT 1 ", "SELECT 1", "transaction"),
        ([], "SELECT 1", "SELECT 1 ", "observe"),
    ],
)
def test_transaction_target_rejects_each_oversized_sql_field(
    setup: list[str], transaction_sql: str, observe_sql: str, field: str
) -> None:
    result = _execute(
        _request(
            setup=setup,
            transaction_sql=transaction_sql,
            observe_sql=observe_sql,
        ),
        SQLiteTransactionTarget(max_sql_bytes=8),
    )

    assert result.infrastructure_error is None
    assert result.exit_code == 2
    assert result.stdout.text == ""
    assert result.stderr.text.strip() == (
        f"protocol_error: {field} statement sql exceeds max_sql_bytes: 8"
    )


def test_real_harness_exercises_sql_budget_as_target_semantics() -> None:
    candidate = SQLiteTransactionTarget(max_sql_bytes=8).as_command_target()
    oracle = SQLiteTransactionTarget(max_sql_bytes=9).as_command_target()
    harness = DifferentialHarness(candidate=candidate, oracle=oracle, timeout_seconds=2.0)
    case = _request(setup=[], transaction_sql="SELECT 1 ", observe_sql="SELECT 1")

    run = harness.evaluate(case)

    assert run.candidate.infrastructure_error is None
    assert run.oracle.infrastructure_error is None
    assert run.candidate.exit_code == 2
    assert run.oracle.exit_code == 0
    assert run.candidate.stderr.text.strip() == (
        "protocol_error: transaction statement sql exceeds max_sql_bytes: 8"
    )
    assert run.comparison.classification == "product_mismatch"
    assert run.signature is not None
    assert run.signature.kind == "product_mismatch"
    assert (
        DifferentialHarness(
            candidate=SQLiteTransactionTarget(max_sql_bytes=8).as_command_target(),
            oracle=SQLiteTransactionTarget(max_sql_bytes=8).as_command_target(),
        ).replay_context_sha256
        != DifferentialHarness(
            candidate=SQLiteTransactionTarget(max_sql_bytes=9).as_command_target(),
            oracle=SQLiteTransactionTarget(max_sql_bytes=9).as_command_target(),
        ).replay_context_sha256
    )
