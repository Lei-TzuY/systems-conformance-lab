from __future__ import annotations

import json

from systems_conformance.harness import DifferentialHarness
from systems_conformance.sqlite_wal_older_reader_release_commit_adapter import (
    SQLiteWALOlderReaderReleaseCommitTarget,
)


def _execute(target: SQLiteWALOlderReaderReleaseCommitTarget, case: bytes = b""):
    return target.as_command_target().execute(
        case,
        timeout_seconds=12.0,
        max_output_bytes=4096,
        max_total_output_bytes=8192,
    )


def test_commit_advances_after_older_reader_release() -> None:
    result = _execute(SQLiteWALOlderReaderReleaseCommitTarget())
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
        "checkpoint_busy_before_older_reader_release": True,
        "older_reader_forced_release": True,
        "newer_reader_snapshot_after_older_release": 61,
        "checkpoint_busy_after_older_reader_release": True,
        "third_writer_committed_value": 63,
        "newer_reader_snapshot_after_third_commit": 61,
        "fresh_observer_value_while_newer_reader_pinned": 63,
        "checkpoint_busy_after_third_commit": True,
        "newer_reader_forced_release": True,
        "checkpoint_busy_after_final_reader_release": False,
        "fresh_reopen_value": 63,
        "fresh_reopen_integrity": "ok",
        "fresh_reopen_checkpoint_busy": False,
    }


def test_older_reader_release_commit_target_rejects_untrusted_input() -> None:
    result = _execute(SQLiteWALOlderReaderReleaseCommitTarget(), b"WRITE")
    assert result.infrastructure_error is None
    assert result.timed_out is False
    assert result.exit_code == 2
    assert result.stdout.text == ""
    assert result.stderr.text.strip() == (
        "protocol_error: WAL older-reader-release commit target requires empty input"
    )


def test_real_harness_repeats_older_reader_release_commit_deterministically() -> None:
    target = SQLiteWALOlderReaderReleaseCommitTarget()
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
