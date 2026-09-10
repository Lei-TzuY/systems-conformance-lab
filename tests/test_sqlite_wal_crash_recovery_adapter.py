from __future__ import annotations

import json

from systems_conformance.harness import DifferentialHarness
from systems_conformance.sqlite_wal_crash_recovery_adapter import (
    SQLiteWALCrashRecoveryTarget,
)


def _execute(target: SQLiteWALCrashRecoveryTarget, case: bytes = b""):
    return target.as_command_target().execute(
        case,
        timeout_seconds=4.0,
        max_output_bytes=4096,
        max_total_output_bytes=8192,
    )


def test_wal_writer_crash_preserves_committed_state_and_allows_recovery() -> None:
    result = _execute(SQLiteWALCrashRecoveryTarget())

    assert result.infrastructure_error is None
    assert result.exit_code == 0, result.stderr.text
    assert result.stderr.text == ""
    assert json.loads(result.stdout.text) == {
        "journal_mode": "wal",
        "writer_checkpoint": "uncommitted_update_ready",
        "writer_terminated": True,
        "recovered_value": 0,
        "fresh_committed_value": 2,
    }


def test_committed_wal_update_survives_writer_crash_before_normal_close() -> None:
    result = _execute(SQLiteWALCrashRecoveryTarget(commit_before_crash=True))

    assert result.infrastructure_error is None
    assert result.exit_code == 0, result.stderr.text
    assert result.stderr.text == ""
    assert json.loads(result.stdout.text) == {
        "journal_mode": "wal",
        "writer_checkpoint": "committed_update_ready",
        "writer_terminated": True,
        "recovered_value": 1,
        "fresh_committed_value": 2,
    }


def test_pinned_reader_survives_uncommitted_writer_crash_and_fresh_commit() -> None:
    result = _execute(SQLiteWALCrashRecoveryTarget(pin_reader_snapshot=True))

    assert result.infrastructure_error is None
    assert result.exit_code == 0, result.stderr.text
    assert result.stderr.text == ""
    assert json.loads(result.stdout.text) == {
        "journal_mode": "wal",
        "writer_checkpoint": "uncommitted_update_ready",
        "writer_terminated": True,
        "recovered_value": 0,
        "fresh_committed_value": 2,
        "reader_snapshot_pinned": True,
        "pinned_reader_value": 0,
        "post_release_value": 2,
    }


def test_pinned_reader_keeps_snapshot_across_committed_writer_crash() -> None:
    result = _execute(
        SQLiteWALCrashRecoveryTarget(
            commit_before_crash=True,
            pin_reader_snapshot=True,
        )
    )

    assert result.infrastructure_error is None
    assert result.exit_code == 0, result.stderr.text
    assert result.stderr.text == ""
    assert json.loads(result.stdout.text) == {
        "journal_mode": "wal",
        "writer_checkpoint": "committed_update_ready",
        "writer_terminated": True,
        "recovered_value": 1,
        "fresh_committed_value": 2,
        "reader_snapshot_pinned": True,
        "pinned_reader_value": 0,
        "post_release_value": 2,
    }


def test_crash_modes_are_bound_into_command_identity() -> None:
    baseline = SQLiteWALCrashRecoveryTarget().as_command_target()
    committed = SQLiteWALCrashRecoveryTarget(commit_before_crash=True).as_command_target()
    pinned = SQLiteWALCrashRecoveryTarget(pin_reader_snapshot=True).as_command_target()
    combined = SQLiteWALCrashRecoveryTarget(
        commit_before_crash=True,
        pin_reader_snapshot=True,
    ).as_command_target()

    assert committed.argv == (*baseline.argv, "--commit-before-crash")
    assert pinned.argv == (*baseline.argv, "--pin-reader-snapshot")
    assert combined.argv == (
        *baseline.argv,
        "--commit-before-crash",
        "--pin-reader-snapshot",
    )


def test_wal_crash_recovery_target_rejects_nonempty_untrusted_input() -> None:
    result = _execute(
        SQLiteWALCrashRecoveryTarget(
            commit_before_crash=True,
            pin_reader_snapshot=True,
        ),
        b"SELECT 1",
    )

    assert result.infrastructure_error is None
    assert result.exit_code == 2
    assert result.stdout.text == ""
    assert (
        result.stderr.text.strip()
        == "protocol_error: SQLite WAL crash recovery target requires empty input"
    )


def test_real_harness_repeats_wal_crash_recovery_deterministically() -> None:
    target = SQLiteWALCrashRecoveryTarget(
        commit_before_crash=True,
        pin_reader_snapshot=True,
    )
    harness = DifferentialHarness(
        candidate=target.as_command_target(),
        oracle=target.as_command_target(),
        timeout_seconds=4.0,
    )

    run = harness.evaluate(b"")

    assert run.candidate.exit_code == 0, run.candidate.stderr.text
    assert run.oracle.exit_code == 0, run.oracle.stderr.text
    assert run.comparison.equivalent is True
    assert run.comparison.classification == "match"
