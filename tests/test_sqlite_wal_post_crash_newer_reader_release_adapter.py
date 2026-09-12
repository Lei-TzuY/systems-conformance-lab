from __future__ import annotations

import json

from systems_conformance.harness import DifferentialHarness
from systems_conformance.sqlite_wal_post_crash_newer_reader_release_adapter import (
    SQLiteWALPostCrashNewerReaderReleaseTarget,
)


def _execute(target: SQLiteWALPostCrashNewerReaderReleaseTarget, case: bytes = b""):
    return target.as_command_target().execute(
        case,
        timeout_seconds=12.0,
        max_output_bytes=4096,
        max_total_output_bytes=8192,
    )


def test_newer_reader_release_after_committed_writer_crash() -> None:
    result = _execute(SQLiteWALPostCrashNewerReaderReleaseTarget())

    assert result.infrastructure_error is None
    assert result.timed_out is False
    assert result.exit_code == 0, result.stderr.text
    assert result.stderr.text == ""
    assert json.loads(result.stdout.text) == {
        "journal_mode": "wal",
        "older_reader_snapshot": 80,
        "first_writer_committed_value": 81,
        "committed_writer_value": 82,
        "committed_writer_forced_crash": True,
        "fresh_observer_value_after_writer_crash": 82,
        "post_crash_reader_snapshot": 82,
        "second_writer_committed_value": 83,
        "checkpoint_busy_with_two_readers": True,
        "post_crash_reader_forced_release": True,
        "older_reader_snapshot_after_newer_release": 80,
        "checkpoint_busy_after_newer_release": True,
        "fresh_observer_value_after_newer_release": 83,
        "third_writer_committed_value": 84,
        "older_reader_snapshot_after_third_commit": 80,
        "checkpoint_busy_after_third_commit": True,
        "fresh_observer_value_while_older_pinned": 84,
        "older_reader_forced_release": True,
        "checkpoint_busy_after_final_release": False,
        "durable_value_before_followup": 84,
        "integrity_before_followup": "ok",
        "followup_commit_value": 85,
        "fresh_reopen_value": 85,
        "fresh_reopen_integrity": "ok",
        "fresh_reopen_checkpoint_busy": False,
    }


def test_post_crash_newer_reader_release_rejects_untrusted_input() -> None:
    result = _execute(SQLiteWALPostCrashNewerReaderReleaseTarget(), b"READ")

    assert result.infrastructure_error is None
    assert result.timed_out is False
    assert result.exit_code == 2
    assert result.stdout.text == ""
    assert result.stderr.text.strip() == (
        "protocol_error: WAL post-crash newer-reader release target requires empty input"
    )


def test_real_harness_repeats_post_crash_newer_reader_release_deterministically() -> None:
    target = SQLiteWALPostCrashNewerReaderReleaseTarget()
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
