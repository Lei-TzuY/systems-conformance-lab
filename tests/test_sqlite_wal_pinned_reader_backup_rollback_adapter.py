from __future__ import annotations

import json

from systems_conformance.harness import DifferentialHarness
from systems_conformance.sqlite_wal_pinned_reader_backup_rollback_adapter import (
    SQLiteWALPinnedReaderBackupRollbackTarget,
)


def _execute(target: SQLiteWALPinnedReaderBackupRollbackTarget, case: bytes = b""):
    return target.as_command_target().execute(
        case,
        timeout_seconds=6.0,
        max_output_bytes=4096,
        max_total_output_bytes=8192,
    )


def test_backup_excludes_uncommitted_writer_after_crash_with_reader_pinned() -> None:
    result = _execute(SQLiteWALPinnedReaderBackupRollbackTarget())

    assert result.infrastructure_error is None
    assert result.exit_code == 0, result.stderr.text
    assert result.stderr.text == ""
    assert json.loads(result.stdout.text) == {
        "journal_mode": "wal",
        "reader_snapshot": 100,
        "first_writer_committed_value": 101,
        "uncommitted_writer_pending_value": 102,
        "writer_forced_crash": True,
        "reader_snapshot_after_writer_crash": 100,
        "fresh_source_value_after_writer_crash": 101,
        "checkpoint_busy_before_backup": True,
        "backup_value_while_reader_pinned": 101,
        "backup_integrity_while_reader_pinned": "ok",
        "reader_snapshot_after_backup": 100,
        "checkpoint_busy_after_backup": True,
        "second_writer_committed_value": 103,
        "reader_snapshot_after_source_commit": 100,
        "fresh_source_value_after_backup_commit": 103,
        "backup_value_after_source_commit": 101,
        "checkpoint_busy_after_source_commit": True,
        "reader_forced_release": True,
        "checkpoint_busy_after_reader_release": False,
        "source_reopen_value": 103,
        "backup_reopen_value": 101,
        "source_reopen_integrity": "ok",
        "backup_reopen_integrity": "ok",
        "backup_after_backup_write": 104,
        "source_after_backup_write": 103,
        "source_followup_commit": 105,
        "final_source_value": 105,
        "final_backup_value": 104,
        "final_source_integrity": "ok",
        "final_backup_integrity": "ok",
    }


def test_pinned_reader_backup_rollback_target_rejects_nonempty_untrusted_input() -> None:
    result = _execute(SQLiteWALPinnedReaderBackupRollbackTarget(), b"SELECT 1")

    assert result.infrastructure_error is None
    assert result.exit_code == 2
    assert result.stdout.text == ""
    assert (
        result.stderr.text.strip()
        == "protocol_error: WAL pinned-reader backup-rollback target requires empty input"
    )


def test_real_harness_repeats_pinned_reader_backup_rollback_deterministically() -> None:
    target = SQLiteWALPinnedReaderBackupRollbackTarget()
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