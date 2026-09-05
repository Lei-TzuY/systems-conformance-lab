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
            "transaction": [{"sql": "INSERT INTO items VALUES (?)", "params": [42]}],
            "observe": _statement("SELECT v FROM items ORDER BY v"),
        },
        separators=(",", ":"),
    ).encode()


def _execute(target: SQLiteTransactionTarget):
    return target.as_command_target().execute(
        _case(),
        timeout_seconds=2.0,
        max_output_bytes=4096,
        max_total_output_bytes=8192,
    )


def test_reopen_mode_observes_committed_file_backed_state() -> None:
    result = _execute(SQLiteTransactionTarget(reopen_before_observe=True))

    assert result.infrastructure_error is None
    assert result.exit_code == 0
    assert result.stderr.text == ""
    assert json.loads(result.stdout.text)["observation"] == {
        "columns": ["v"],
        "rows": [[42]],
    }


def test_reopen_mode_observes_rolled_back_file_backed_state() -> None:
    result = _execute(
        SQLiteTransactionTarget(finalize="rollback", reopen_before_observe=True)
    )

    assert result.infrastructure_error is None
    assert result.exit_code == 0
    assert json.loads(result.stdout.text)["observation"] == {
        "columns": ["v"],
        "rows": [],
    }


def test_reopen_mode_changes_command_identity() -> None:
    in_memory = SQLiteTransactionTarget().as_command_target()
    reopened = SQLiteTransactionTarget(reopen_before_observe=True).as_command_target()

    assert in_memory.argv != reopened.argv
    assert "--same-connection-observe" in in_memory.argv
    assert "--reopen-before-observe" in reopened.argv


def test_reopen_mode_rejects_non_bool_configuration() -> None:
    with pytest.raises(TypeError, match="reopen_before_observe must be a bool"):
        SQLiteTransactionTarget(reopen_before_observe=1)  # type: ignore[arg-type]


def test_real_harness_distinguishes_commit_from_rollback_after_reopen() -> None:
    candidate = SQLiteTransactionTarget(
        finalize="commit", reopen_before_observe=True
    ).as_command_target()
    oracle = SQLiteTransactionTarget(
        finalize="rollback", reopen_before_observe=True
    ).as_command_target()
    harness = DifferentialHarness(candidate=candidate, oracle=oracle, timeout_seconds=2.0)

    run = harness.evaluate(_case())

    assert run.candidate.infrastructure_error is None
    assert run.oracle.infrastructure_error is None
    assert run.candidate.exit_code == 0
    assert run.oracle.exit_code == 0
    assert json.loads(run.candidate.stdout.text)["observation"]["rows"] == [[42]]
    assert json.loads(run.oracle.stdout.text)["observation"]["rows"] == []
    assert run.comparison.classification == "product_mismatch"
    assert run.signature is not None
    assert run.signature.kind == "product_mismatch"
