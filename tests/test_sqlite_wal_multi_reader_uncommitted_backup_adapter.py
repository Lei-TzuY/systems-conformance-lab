from __future__ import annotations

import json

from systems_conformance.harness import DifferentialHarness
from systems_conformance.sqlite_wal_multi_reader_uncommitted_backup_adapter import (
    SQLiteWALMultiReaderUncommittedBackupTarget,
)


def _execute(target: SQLiteWALMultiReaderUncommittedBackupTarget, case: bytes = b""):
    return target.as_command_target().execute(
        case,
        timeout_seconds=6.0,
        max_output_bytes=4096,
        max_total_output_bytes=8192,
    )


def test_backup_excludes_uncommitted_crash_across_two_reader_generations() -> None:
    result = _execute(SQLiteWALMultiReaderUncommittedBackupTarget())

    assert result.infrastructure_error is None
    assert result.exit_code == 0, result.stderr.text
    assert result.stderr.text == ""
    assert json.loads(result.stdout.text) == {
        "journal_mode": "wal",
        "older_reader_snapshot": 120,
        "first_writer_committed_value": 121,
        "newer_reader_snapshot": 121,
        "uncommitted_writer_pending_value": 122,
        "uncommitted_writer_forced_crash": True,
        "older_reader_snapshot_after_writer_crash": 120,
        "newer_reader_snapshot_after_writer_crash": 121,
        "fresh_source_value_after_writer_crash": 121,
        "checkpoint_busy_before_backup": True,
        "backup_value_while_readers_pinned": 121,
        "backup_integrity_while_readers_pinned": "ok",
        "older_reader_snapshot_after_backup": 120,
        "newer_reader_snapshot_after_backup": 121,
        "checkpoint_busy_after_backup": True,
        "older_reader_forced_release": True,
        "newer_reader_snapshot_after_older_release": 121,
        "checkpoint_busy_after_older_release": True,
        "second_writer_committed_value": 123,
        "newer_reader_snapshot_after_second_commit": 121,
        "fresh_source_value_after_second_commit": 123,
        "backup_value_after_source_commit": 121,
        "checkpoint_busy_after_second_commit": True,
        "newer_reader_forced_release": True,
        "checkpoint_busy_after_final_release": False,
        "source_reopen_value": 123,
        "backup_reopen_value": 121,
        "source_reopen_integrity": "ok",
        "backup_reopen_integrity": "ok",
        "backup_after_backup_write": 124,
        "source_after_backup_write": 123,
        "source_followup_commit": 125,
        "final_source_value": 125,
        "final_backup_value": 124,
        "final_source_integrity": "ok",
        "final_backup_integrity": "ok",
    }


def test_multi_reader_uncommitted_backup_rejects_nonempty_input() -> None:
    result = _execute(SQLiteWALMultiReaderUncommittedBackupTarget(), b"SELECT 1")

    assert result.infrastructure_error is None
    assert result.exit_code == 2
    assert result.stdout.text == ""
    assert (
        result.stderr.text.strip()
        == "protocol_error: WAL multi-reader uncommitted backup target requires empty input"
    )


def test_real_harness_repeats_uncommitted_backup_deterministically() -> None:
    target = SQLiteWALMultiReaderUncommittedBackupTarget()
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
