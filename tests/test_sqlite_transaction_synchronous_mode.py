from __future__ import annotations

import json

import pytest

from systems_conformance import DifferentialHarness, SQLiteTransactionTarget


def _statement(sql: str) -> dict[str, object]:
    return {"sql": sql, "params": []}


def _case() -> bytes:
    return json.dumps(
        {
            "setup": ["CREATE TABLE items(v INTEGER)"],
            "transaction": [
                _statement("INSERT INTO items VALUES (7)"),
                _statement("INSERT INTO items VALUES (11)"),
            ],
            "observe": _statement("SELECT v FROM items ORDER BY v"),
        },
        separators=(",", ":"),
    ).encode()


def test_sqlite_transaction_target_rejects_unknown_synchronous_mode() -> None:
    with pytest.raises(ValueError, match="synchronous must be 'normal' or 'full'"):
        SQLiteTransactionTarget(synchronous="off")  # type: ignore[arg-type]


def test_wal_normal_transaction_persists_committed_rows_across_reopen() -> None:
    result = SQLiteTransactionTarget(
        journal_mode="wal",
        synchronous="normal",
        reopen_before_observe=True,
    ).as_command_target().execute(
        _case(),
        timeout_seconds=2.0,
        max_output_bytes=4096,
        max_total_output_bytes=8192,
    )

    assert result.infrastructure_error is None
    assert result.exit_code == 0
    assert result.stderr.text == ""
    assert json.loads(result.stdout.text)["observation"] == {
        "columns": ["v"],
        "rows": [[7], [11]],
    }


@pytest.mark.parametrize("finalize", ["commit", "rollback"])
def test_wal_normal_and_full_have_matching_reopen_semantics(finalize: str) -> None:
    harness = DifferentialHarness(
        candidate=SQLiteTransactionTarget(
            finalize=finalize,  # type: ignore[arg-type]
            journal_mode="wal",
            synchronous="normal",
            reopen_before_observe=True,
        ).as_command_target(),
        oracle=SQLiteTransactionTarget(
            finalize=finalize,  # type: ignore[arg-type]
            journal_mode="wal",
            synchronous="full",
            reopen_before_observe=True,
        ).as_command_target(),
        timeout_seconds=2.0,
    )

    run = harness.evaluate(_case())

    assert run.candidate.infrastructure_error is None
    assert run.oracle.infrastructure_error is None
    assert run.candidate.exit_code == 0
    assert run.oracle.exit_code == 0
    assert run.comparison.classification == "match"
    assert run.signature is None
    expected_rows = [[7], [11]] if finalize == "commit" else []
    assert json.loads(run.candidate.stdout.text)["observation"]["rows"] == expected_rows
    assert json.loads(run.oracle.stdout.text)["observation"]["rows"] == expected_rows
