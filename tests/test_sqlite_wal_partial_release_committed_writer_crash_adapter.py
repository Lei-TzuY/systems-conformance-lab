from __future__ import annotations

import json

from systems_conformance.harness import DifferentialHarness
from systems_conformance.sqlite_wal_partial_release_committed_writer_crash_adapter import (
    SQLiteWALPartialReleaseCommittedWriterCrashTarget,
)


def _execute(
    target: SQLiteWALPartialReleaseCommittedWriterCrashTarget, case: bytes = b""
):
    return target.as_command_target().execute(
        case,
        timeout_seconds=12.0,
        max_output_bytes=4096,
        max_total_output_bytes=8192,
    )


def test_committed_writer_survives_crash_after_partial_reader_release() -> None:
    result = _execute(SQLiteWALPartialReleaseCommittedWriterCrashTarget())

    assert result.infrastructure_error is None
    assert result.timed_out is False
    assert result.exit_code == 0, result.stderr.text
    assert result.stderr.text == ""
    assert json.loads(result.stdout.text) == {
        "journal_mode": "wal",
        "older_reader_snapshot": 60,
        "first_writer_committed_value": 61,
        "newer_reader_snapshot": 61,
        "second_writer_committed_value": 62,
        "checkpoint_busy_before_partial_release": True,
        "newer_reader_forced_release": True,
        "checkpoint_busy_after_newer_release": True,
        "committed_writer_value": 63,
        "writer_forced_crash_after_commit": True,
        "older_reader_snapshot_after_writer_crash": 60,
        "fresh_observer_value_after_writer_crash": 63,
        "checkpoint_busy_after_writer_crash": True,
        "older_reader_forced_release": True,
        "checkpoint_busy_after_final_reader_release": False,
        "durable_value_before_followup": 63,
        "integrity_before_followup": "ok",
        "post_crash_write_value": 64,
        "fresh_reopen_value": 64,
        "fresh_reopen_integrity": "ok",
        "fresh_reopen_checkpoint_busy": False,
    }


def test_partial_release_committed_writer_crash_target_rejects_untrusted_input() -> None:
    result = _execute(SQLiteWALPartialReleaseCommittedWriterCrashTarget(), b"COMMIT")

    assert result.infrastructure_error is None
    assert result.timed_out is False
    assert result.exit_code == 2
    assert result.stdout.text == ""
    assert result.stderr.text.strip() == (
        "protocol_error: WAL partial-release committed-writer crash target requires empty input"
    )


def test_real_harness_repeats_committed_writer_crash_deterministically() -> None:
    target = SQLiteWALPartialReleaseCommittedWriterCrashTarget()
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
