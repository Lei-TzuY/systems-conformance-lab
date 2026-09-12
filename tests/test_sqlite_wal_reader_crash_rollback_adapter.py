from __future__ import annotations

import json

from systems_conformance.harness import DifferentialHarness
from systems_conformance.sqlite_wal_reader_crash_rollback_adapter import (
    SQLiteWALReaderCrashRollbackTarget,
)


def _execute(target: SQLiteWALReaderCrashRollbackTarget, case: bytes = b""):
    return target.as_command_target().execute(
        case,
        timeout_seconds=12.0,
        max_output_bytes=4096,
        max_total_output_bytes=8192,
    )


def test_reader_crash_preserves_writer_rollback_and_followup_write() -> None:
    result = _execute(SQLiteWALReaderCrashRollbackTarget())

    assert result.infrastructure_error is None
    assert result.timed_out is False
    assert result.exit_code == 0, result.stderr.text
    assert result.stderr.text == ""
    assert json.loads(result.stdout.text) == {
        "journal_mode": "wal",
        "reader_initial_value": 10,
        "writer_pending_value": 11,
        "reader_snapshot_while_writer_active": 10,
        "reader_forced_crash": True,
        "writer_value_after_rollback": 10,
        "fresh_reopen_value_after_rollback": 10,
        "fresh_reopen_integrity_after_rollback": "ok",
        "fresh_reopen_checkpoint_busy_after_rollback": False,
        "post_rollback_write_value": 12,
        "final_durable_value": 12,
        "final_integrity": "ok",
        "final_checkpoint_busy": False,
    }


def test_reader_crash_rollback_target_rejects_nonempty_untrusted_input() -> None:
    result = _execute(SQLiteWALReaderCrashRollbackTarget(), b"ROLLBACK")

    assert result.infrastructure_error is None
    assert result.timed_out is False
    assert result.exit_code == 2
    assert result.stdout.text == ""
    assert result.stderr.text.strip() == (
        "protocol_error: WAL reader crash rollback target requires empty input"
    )


def test_real_harness_repeats_reader_crash_rollback_target_deterministically() -> None:
    target = SQLiteWALReaderCrashRollbackTarget()
    harness = DifferentialHarness(
        candidate=target.as_command_target(),
        oracle=target.as_command_target(),
        timeout_seconds=12.0,
    )

    run = harness.evaluate(b"")

    assert run.candidate.exit_code == 0, run.candidate.stderr.text
    assert run.oracle.exit_code == 0, run.oracle.stderr.text
    assert run.comparison.equivalent is True
    assert run.comparison.classification == "match"
