from __future__ import annotations

import json

from systems_conformance.harness import DifferentialHarness
from systems_conformance.sqlite_wal_backup_recovery_adapter import (
    SQLiteWALBackupRecoveryTarget,
)


def _execute(target: SQLiteWALBackupRecoveryTarget, case: bytes = b""):
    return target.as_command_target().execute(
        case,
        timeout_seconds=6.0,
        max_output_bytes=4096,
        max_total_output_bytes=8192,
    )


def test_online_backup_round_trips_recovered_wal_state_through_child_process() -> None:
    result = _execute(SQLiteWALBackupRecoveryTarget())

    assert result.infrastructure_error is None
    assert result.exit_code == 0, result.stderr.text
    assert result.stderr.text == ""
    assert json.loads(result.stdout.text) == {
        "journal_mode": "wal",
        "writer_checkpoint": "committed_update_ready",
        "writer_terminated": True,
        "recovered_value": 1,
        "post_recovery_value": 2,
        "checkpoint_busy": False,
        "source_integrity": "ok",
        "backup_process": "child",
        "backup_value": 2,
        "backup_integrity": "ok",
        "backup_reopened": True,
        "source_after_source_write": 3,
        "backup_after_source_write": 2,
        "backup_after_backup_write": 4,
        "source_after_backup_write": 3,
        "independent_writes_integrity": "ok",
        "source_deleted": True,
        "detached_backup_process": "child",
        "detached_backup_value": 5,
        "detached_backup_integrity": "ok",
        "detached_backup_reopened": True,
        "detached_backup_wal_mode": "wal",
        "detached_backup_wal_writer_terminated": True,
        "detached_backup_wal_value": 6,
        "detached_backup_wal_integrity": "ok",
        "detached_backup_wal_checkpoint_busy": False,
    }


def test_backup_recovery_target_rejects_nonempty_untrusted_input() -> None:
    result = _execute(SQLiteWALBackupRecoveryTarget(), b"SELECT 1")

    assert result.infrastructure_error is None
    assert result.exit_code == 2
    assert result.stdout.text == ""
    assert (
        result.stderr.text.strip()
        == "protocol_error: SQLite WAL backup recovery target requires empty input"
    )


def test_real_harness_repeats_wal_backup_recovery_deterministically() -> None:
    target = SQLiteWALBackupRecoveryTarget()
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
