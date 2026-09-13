from __future__ import annotations

import json

from systems_conformance.harness import DifferentialHarness
from systems_conformance.sqlite_wal_multi_reader_backup_adapter import (
    SQLiteWALMultiReaderBackupTarget,
)


def _execute(target: SQLiteWALMultiReaderBackupTarget, case: bytes = b""):
    return target.as_command_target().execute(
        case,
        timeout_seconds=6.0,
        max_output_bytes=4096,
        max_total_output_bytes=8192,
    )


def test_backup_captures_latest_commit_across_two_pinned_reader_generations() -> None:
    result = _execute(SQLiteWALMultiReaderBackupTarget())

    assert result.infrastructure_error is None
    assert result.exit_code == 0, result.stderr.text
    assert result.stderr.text == ""
    assert json.loads(result.stdout.text) == {
        "journal_mode": "wal",
        "older_reader_snapshot": 110,
        "first_writer_committed_value": 111,
        "newer_reader_snapshot": 111,
        "committed_writer_value": 112,
        "committed_writer_forced_crash": True,
        "older_reader_snapshot_after_writer_crash": 110,
        "newer_reader_snapshot_after_writer_crash": 111,
        "fresh_source_value_after_writer_crash": 112,
        "checkpoint_busy_before_backup": True,
        "backup_value_while_readers_pinned": 112,
        "backup_integrity_while_readers_pinned": "ok",
        "older_reader_snapshot_after_backup": 110,
        "newer_reader_snapshot_after_backup": 111,
        "checkpoint_busy_after_backup": True,
        "older_reader_forced_release": True,
        "newer_reader_snapshot_after_older_release": 111,
        "checkpoint_busy_after_older_release": True,
        "second_writer_committed_value": 113,
        "newer_reader_snapshot_after_second_commit": 111,
        "fresh_source_value_after_second_commit": 113,
        "backup_value_after_source_commit": 112,
        "checkpoint_busy_after_second_commit": True,
        "newer_reader_forced_release": True,
        "checkpoint_busy_after_final_release": False,
        "source_reopen_value": 113,
        "backup_reopen_value": 112,
        "source_reopen_integrity": "ok",
        "backup_reopen_integrity": "ok",
        "backup_after_backup_write": 114,
        "source_after_backup_write": 113,
        "source_followup_commit": 115,
        "final_source_value": 115,
        "final_backup_value": 114,
        "final_source_integrity": "ok",
        "final_backup_integrity": "ok",
    }


def test_multi_reader_backup_target_rejects_nonempty_untrusted_input() -> None:
    result = _execute(SQLiteWALMultiReaderBackupTarget(), b"SELECT 1")

    assert result.infrastructure_error is None
    assert result.exit_code == 2
    assert result.stdout.text == ""
    assert (
        result.stderr.text.strip()
        == "protocol_error: WAL multi-reader backup target requires empty input"
    )


def test_real_harness_repeats_multi_reader_backup_deterministically() -> None:
    target = SQLiteWALMultiReaderBackupTarget()
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
