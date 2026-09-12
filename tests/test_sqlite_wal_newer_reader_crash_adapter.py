from __future__ import annotations

import json

from systems_conformance.harness import DifferentialHarness
from systems_conformance.sqlite_wal_newer_reader_crash_adapter import SQLiteWALNewerReaderCrashTarget


def _execute(target: SQLiteWALNewerReaderCrashTarget, case: bytes = b""):
    return target.as_command_target().execute(case, timeout_seconds=12.0, max_output_bytes=4096, max_total_output_bytes=8192)


def test_newer_reader_crash_preserves_older_checkpoint_constraint() -> None:
    result = _execute(SQLiteWALNewerReaderCrashTarget())
    assert result.infrastructure_error is None
    assert result.timed_out is False
    assert result.exit_code == 0, result.stderr.text
    assert result.stderr.text == ""
    assert json.loads(result.stdout.text) == {
        "journal_mode": "wal",
        "older_reader_snapshot": 20,
        "first_writer_committed_value": 21,
        "newer_reader_snapshot": 21,
        "second_writer_committed_value": 22,
        "checkpoint_busy_with_two_readers": True,
        "newer_reader_forced_crash": True,
        "older_reader_snapshot_after_newer_crash": 20,
        "checkpoint_busy_after_newer_reader_crash": True,
        "older_reader_forced_crash": True,
        "checkpoint_busy_after_final_reader_crash": False,
        "post_crash_write_value": 23,
        "fresh_reopen_value": 23,
        "fresh_reopen_integrity": "ok",
        "fresh_reopen_checkpoint_busy": False,
    }


def test_newer_reader_crash_target_rejects_nonempty_untrusted_input() -> None:
    result = _execute(SQLiteWALNewerReaderCrashTarget(), b"READ")
    assert result.infrastructure_error is None
    assert result.timed_out is False
    assert result.exit_code == 2
    assert result.stdout.text == ""
    assert result.stderr.text.strip() == "protocol_error: WAL newer-reader crash target requires empty input"


def test_real_harness_repeats_newer_reader_crash_target_deterministically() -> None:
    target = SQLiteWALNewerReaderCrashTarget()
    harness = DifferentialHarness(candidate=target.as_command_target(), oracle=target.as_command_target(), timeout_seconds=12.0)
    run = harness.evaluate(b"")
    assert run.candidate.exit_code == 0, run.candidate.stderr.text
    assert run.oracle.exit_code == 0, run.oracle.stderr.text
    assert run.candidate.infrastructure_error is None
    assert run.oracle.infrastructure_error is None
    assert run.comparison.equivalent is True
    assert run.comparison.classification == "match"
