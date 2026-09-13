from __future__ import annotations

import json

from systems_conformance.harness import DifferentialHarness
from systems_conformance.sqlite_wal_pinned_reader_backup_adapter import (
    SQLiteWALPinnedReaderBackupTarget,
)


def _execute(target: SQLiteWALPinnedReaderBackupTarget, case: bytes = b""):
    return target.as_command_target().execute(
        case,
        timeout_seconds=6.0,
        max_output_bytes=4096,
        max_total_output_bytes=8192,
    )


def test_backup_captures_latest_commit_while_stale_reader_remains_pinned() -> None:
    result = _execute(SQLiteWALPinnedReaderBackupTarget())

    assert result.infrastructure_error is None
    assert result.exit_code == 0, result.stderr.text
    assert result.stderr.text == ""
    assert json.loads(result.stdout.text) == {
        "journal_mode": "wal",
        "reader_snapshot": 90,
        "first_writer_committed_value": 91,
        "committed_writer_value": 92,
        "committed_writer_forced_crash": True,
        "reader_snapshot_after_writer_crash": 90,
        "fresh_source_value_after_writer_crash": 92,
        "checkpoint_busy_before_backup": True,
        "backup_value_while_reader_pinned": 92,
        "backup_integrity_while_reader_pinned": "ok",
        "reader_snapshot_after_backup": 90,
        "checkpoint_busy_after_backup": True,
        "second_writer_committed_value": 93,
        "reader_snapshot_after_source_commit": 90,
        "fresh_source_value_after_backup_commit": 93,
        "backup_value_after_source_commit": 92,
        "checkpoint_busy_after_source_commit": True,
        "reader_forced_release": True,
        "checkpoint_busy_after_reader_release": False,
        "source_reopen_value": 93,
        "backup_reopen_value": 92,
        "source_reopen_integrity": "ok",
        "backup_reopen_integrity": "ok",
        "backup_after_backup_write": 94,
        "source_after_backup_write": 93,
        "source_followup_commit": 95,
        "final_source_value": 95,
        "final_backup_value": 94,
        "final_source_integrity": "ok",
        "final_backup_integrity": "ok",
    }


def test_pinned_reader_backup_target_rejects_nonempty_untrusted_input() -> None:
    result = _execute(SQLiteWALPinnedReaderBackupTarget(), b"SELECT 1")

    assert result.infrastructure_error is None
    assert result.exit_code == 2
    assert result.stdout.text == ""
    assert (
        result.stderr.text.strip()
        == "protocol_error: WAL pinned-reader backup target requires empty input"
    )


def test_real_harness_repeats_pinned_reader_backup_deterministically() -> None:
    target = SQLiteWALPinnedReaderBackupTarget()
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
