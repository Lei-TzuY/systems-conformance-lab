from __future__ import annotations

import json

from systems_conformance.harness import DifferentialHarness
from systems_conformance.sqlite_wal_backup_rollback_adapter import (
    SQLiteWALBackupRollbackTarget,
)


def _execute(target: SQLiteWALBackupRollbackTarget, case: bytes = b""):
    return target.as_command_target().execute(
        case,
        timeout_seconds=8.0,
        max_output_bytes=4096,
        max_total_output_bytes=8192,
    )


def test_detached_backup_rollback_remains_durable() -> None:
    result = _execute(SQLiteWALBackupRollbackTarget())

    assert result.infrastructure_error is None
    assert result.timed_out is False
    assert result.exit_code == 0, result.stderr.text
    assert result.stderr.text == ""
    assert json.loads(result.stdout.text) == {
        "source_deleted": True,
        "backup_process": "detached",
        "journal_mode": "wal",
        "uncommitted_writer_terminated": True,
        "recovered_value": 6,
        "integrity": "ok",
        "checkpoint_busy": False,
        "post_rollback_committed_value": 8,
        "post_rollback_committed_writer_terminated": True,
        "fresh_reopen_value": 8,
        "fresh_reopen_integrity": "ok",
        "fresh_reopen_checkpoint_busy": False,
    }


def test_backup_rollback_target_rejects_nonempty_untrusted_input() -> None:
    result = _execute(SQLiteWALBackupRollbackTarget(), b"SELECT 1")

    assert result.infrastructure_error is None
    assert result.timed_out is False
    assert result.exit_code == 2
    assert result.stdout.text == ""
    assert (
        result.stderr.text.strip()
        == "protocol_error: SQLite WAL backup rollback target requires empty input"
    )


def test_real_harness_repeats_backup_rollback_deterministically() -> None:
    target = SQLiteWALBackupRollbackTarget()
    harness = DifferentialHarness(
        candidate=target.as_command_target(),
        oracle=target.as_command_target(),
        timeout_seconds=8.0,
    )

    run = harness.evaluate(b"")

    assert run.candidate.exit_code == 0, run.candidate.stderr.text
    assert run.oracle.exit_code == 0, run.oracle.stderr.text
    assert run.comparison.equivalent is True
    assert run.comparison.classification == "match"
