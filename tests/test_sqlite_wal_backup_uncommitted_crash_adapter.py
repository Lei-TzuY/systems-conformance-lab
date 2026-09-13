from __future__ import annotations

import json

from systems_conformance.harness import DifferentialHarness
from systems_conformance.sqlite_wal_backup_uncommitted_crash_adapter import (
    SQLiteWALBackupUncommittedCrashTarget,
)


def _execute(target: SQLiteWALBackupUncommittedCrashTarget, case: bytes = b""):
    return target.as_command_target().execute(
        case,
        timeout_seconds=6.0,
        max_output_bytes=4096,
        max_total_output_bytes=8192,
    )


def test_detached_backup_rolls_back_uncommitted_writer_after_source_deletion() -> None:
    result = _execute(SQLiteWALBackupUncommittedCrashTarget())

    assert result.infrastructure_error is None
    assert result.exit_code == 0, result.stderr.text
    assert result.stderr.text == ""
    assert json.loads(result.stdout.text) == {
        "source_journal_mode": "wal",
        "source_value_before_backup": 201,
        "backup_initial_value": 201,
        "backup_initial_integrity": "ok",
        "source_value_after_backup": 202,
        "backup_value_after_source_commit": 201,
        "source_deleted": True,
        "uncommitted_backup_pending_value": 203,
        "uncommitted_backup_writer_forced_crash": True,
        "backup_wal_mode_after_crash": "wal",
        "backup_value_after_crash": 201,
        "backup_integrity_after_crash": "ok",
        "checkpoint_busy_after_crash": False,
        "backup_followup_commit": 204,
        "backup_integrity_after_followup": "ok",
        "final_backup_value": 204,
        "final_backup_integrity": "ok",
    }


def test_detached_backup_uncommitted_crash_rejects_nonempty_input() -> None:
    result = _execute(SQLiteWALBackupUncommittedCrashTarget(), b"SELECT 1")

    assert result.infrastructure_error is None
    assert result.exit_code == 2
    assert result.stdout.text == ""
    assert (
        result.stderr.text.strip()
        == "protocol_error: WAL backup uncommitted crash target requires empty input"
    )


def test_real_harness_repeats_detached_backup_crash_deterministically() -> None:
    target = SQLiteWALBackupUncommittedCrashTarget()
    harness = DifferentialHarness(
        candidate=target.as_command_target(),
        oracle=target.as_command_target(),
        timeout_seconds=6.0,
    )

    run = harness.evaluate(b"")

    assert run.candidate.exit_code == 0, run.candidate.stderr.text
    assert run.oracle.exit_code == 0, run.oracle.stderr.text
    assert run.comparison.equivalent is True
    assert run.comparison.classification == "match"
