from __future__ import annotations

import json

from systems_conformance.harness import DifferentialHarness
from systems_conformance.sqlite_wal_post_crash_reader_admission_adapter import (
    SQLiteWALPostCrashReaderAdmissionTarget,
)


def _execute(target: SQLiteWALPostCrashReaderAdmissionTarget, case: bytes = b""):
    return target.as_command_target().execute(
        case,
        timeout_seconds=12.0,
        max_output_bytes=4096,
        max_total_output_bytes=8192,
    )


def test_reader_admission_after_committed_writer_crash() -> None:
    result = _execute(SQLiteWALPostCrashReaderAdmissionTarget())

    assert result.infrastructure_error is None
    assert result.timed_out is False
    assert result.exit_code == 0, result.stderr.text
    assert result.stderr.text == ""
    assert json.loads(result.stdout.text) == {
        "journal_mode": "wal",
        "older_reader_snapshot": 70,
        "first_writer_committed_value": 71,
        "committed_writer_value": 72,
        "committed_writer_forced_crash": True,
        "fresh_observer_value_after_writer_crash": 72,
        "post_crash_reader_snapshot": 72,
        "second_writer_committed_value": 73,
        "checkpoint_busy_with_two_readers": True,
        "older_reader_forced_release": True,
        "post_crash_reader_snapshot_after_older_release": 72,
        "checkpoint_busy_after_older_release": True,
        "fresh_observer_value_while_reader_pinned": 73,
        "post_crash_reader_forced_release": True,
        "checkpoint_busy_after_final_release": False,
        "durable_value_before_followup": 73,
        "integrity_before_followup": "ok",
        "followup_commit_value": 74,
        "fresh_reopen_value": 74,
        "fresh_reopen_integrity": "ok",
        "fresh_reopen_checkpoint_busy": False,
    }


def test_post_crash_reader_admission_rejects_untrusted_input() -> None:
    result = _execute(SQLiteWALPostCrashReaderAdmissionTarget(), b"READ")

    assert result.infrastructure_error is None
    assert result.timed_out is False
    assert result.exit_code == 2
    assert result.stdout.text == ""
    assert result.stderr.text.strip() == (
        "protocol_error: WAL post-crash reader admission target requires empty input"
    )


def test_real_harness_repeats_post_crash_reader_admission_deterministically() -> None:
    target = SQLiteWALPostCrashReaderAdmissionTarget()
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
