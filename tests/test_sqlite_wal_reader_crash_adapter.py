from __future__ import annotations

import json

from systems_conformance.harness import DifferentialHarness
from systems_conformance.sqlite_wal_reader_crash_adapter import SQLiteWALReaderCrashTarget


def _execute(target: SQLiteWALReaderCrashTarget, case: bytes = b""):
    return target.as_command_target().execute(
        case,
        timeout_seconds=12.0,
        max_output_bytes=4096,
        max_total_output_bytes=8192,
    )


def test_reader_crash_releases_snapshot_for_recovery() -> None:
    result = _execute(SQLiteWALReaderCrashTarget())

    assert result.infrastructure_error is None
    assert result.timed_out is False
    assert result.exit_code == 0, result.stderr.text
    assert result.stderr.text == ""
    assert json.loads(result.stdout.text) == {
        "journal_mode": "wal",
        "reader_initial_value": 6,
        "writer_committed_value": 8,
        "reader_snapshot_after_commit": 6,
        "reader_forced_crash": True,
        "fresh_reopen_value": 8,
        "fresh_reopen_integrity": "ok",
        "post_reader_crash_write_value": 9,
        "post_reader_crash_write_durable": 9,
        "fresh_reopen_checkpoint_busy": False,
    }


def test_reader_crash_target_rejects_nonempty_untrusted_input() -> None:
    result = _execute(SQLiteWALReaderCrashTarget(), b"READ")

    assert result.infrastructure_error is None
    assert result.timed_out is False
    assert result.exit_code == 2
    assert result.stdout.text == ""
    assert result.stderr.text.strip() == (
        "protocol_error: WAL reader crash target requires empty input"
    )


def test_real_harness_repeats_reader_crash_target_deterministically() -> None:
    target = SQLiteWALReaderCrashTarget()
    harness = DifferentialHarness(
        candidate=target.as_command_target(),
        oracle=target.as_command_target(),
        timeout_seconds=12.0,
    )

    run = harness.evaluate(b"")

    assert run.candidate.exit_code == 0, run.candidate.stderr.text
    assert run.oracle.exit_code == 0, run.oracle.stderr.text
    assert run.comparison.equivalent is True
    assert run.comparison.classification == "match"
