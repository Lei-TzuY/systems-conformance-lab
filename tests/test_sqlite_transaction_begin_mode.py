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
                _statement("INSERT INTO items VALUES (5)"),
                _statement("INSERT INTO items VALUES (13)"),
            ],
            "observe": _statement("SELECT v FROM items ORDER BY v"),
        },
        separators=(",", ":"),
    ).encode()


def test_sqlite_transaction_target_rejects_unknown_begin_mode() -> None:
    with pytest.raises(
        ValueError,
        match="begin_mode must be 'deferred', 'immediate', or 'exclusive'",
    ):
        SQLiteTransactionTarget(begin_mode="optimistic")  # type: ignore[arg-type]


@pytest.mark.parametrize("begin_mode", ["immediate", "exclusive"])
@pytest.mark.parametrize("finalize", ["commit", "rollback"])
def test_wal_begin_modes_match_deferred_reopen_semantics(
    begin_mode: str, finalize: str
) -> None:
    harness = DifferentialHarness(
        candidate=SQLiteTransactionTarget(
            finalize=finalize,  # type: ignore[arg-type]
            begin_mode=begin_mode,  # type: ignore[arg-type]
            journal_mode="wal",
            synchronous="full",
            reopen_before_observe=True,
        ).as_command_target(),
        oracle=SQLiteTransactionTarget(
            finalize=finalize,  # type: ignore[arg-type]
            begin_mode="deferred",
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
    expected_rows = [[5], [13]] if finalize == "commit" else []
    assert json.loads(run.candidate.stdout.text)["observation"]["rows"] == expected_rows
    assert json.loads(run.oracle.stdout.text)["observation"]["rows"] == expected_rows
