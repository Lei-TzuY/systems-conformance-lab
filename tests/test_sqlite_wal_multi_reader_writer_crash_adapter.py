from __future__ import annotations

import json

from systems_conformance.harness import DifferentialHarness
from systems_conformance.sqlite_wal_multi_reader_writer_crash_adapter import (
    SQLiteWALMultiReaderWriterCrashTarget,
)


def _execute(target: SQLiteWALMultiReaderWriterCrashTarget, case: bytes = b""):
    return target.as_command_target().execute(
        case,
        timeout_seconds=12.0,
        max_output_bytes=4096,
        max_total_output_bytes=8192,
    )


def test_writer_crash_preserves_multi_reader_checkpoint_constraints() -> None:
    result = _execute(SQLiteWALMultiReaderWriterCrashTarget())

    assert result.infrastructure_error is None
    assert result.timed_out is False
    assert result.exit_code == 0, result.stderr.text
    assert result.stderr.text == ""
    assert json.loads(result.stdout.text) == {
        "journal_mode": "wal",
        "older_reader_snapshot": 30,
        "first_writer_committed_value": 31,
        "newer_reader_snapshot": 31,
        "second_writer_committed_value": 32,
        "checkpoint_busy_before_writer_crash": True,
        "uncommitted_writer_pending_value": 33,
        "writer_forced_crash": True,
        "older_reader_snapshot_after_writer_crash": 30,
        "newer_reader_snapshot_after_writer_crash": 31,
        "checkpoint_busy_after_writer_crash": True,
        "newer_reader_forced_crash": True,
        "checkpoint_busy_after_newer_reader_crash": True,
        "older_reader_forced_crash": True,
        "checkpoint_busy_after_final_reader_crash": False,
        "post_crash_write_value": 34,
        "fresh_reopen_value": 34,
        "fresh_reopen_integrity": "ok",
        "fresh_reopen_checkpoint_busy": False,
    }


def test_multi_reader_writer_crash_target_rejects_nonempty_untrusted_input() -> None:
    result = _execute(SQLiteWALMultiReaderWriterCrashTarget(), b"WRITE")

    assert result.infrastructure_error is None
    assert result.timed_out is False
    assert result.exit_code == 2
    assert result.stdout.text == ""
    assert result.stderr.text.strip() == (
        "protocol_error: WAL multi-reader writer-crash target requires empty input"
    )


def test_real_harness_repeats_multi_reader_writer_crash_deterministically() -> None:
    target = SQLiteWALMultiReaderWriterCrashTarget()
    harness = DifferentialHarness(
        candidate=target.as_command_target(),
        oracle=target.as_command_target(),
        timeout_seconds=12.0,
    )

    run = harness.evaluate(b"")

    assert run.candidate.exit_code == 0, run.candidate.stderr.text
    assert run.oracle.exit_code == 0, run.oracle.stderr.text
    assert run.candidate.infrastructure_error is None
    assert run.oracle.infrastructure_error is None
    assert run.comparison.equivalent is True
    assert run.comparison.classification == "match"
