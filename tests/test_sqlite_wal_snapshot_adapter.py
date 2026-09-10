from __future__ import annotations

import json

from systems_conformance.harness import DifferentialHarness
from systems_conformance.sqlite_wal_snapshot_adapter import SQLiteWALSnapshotTarget


def _execute(target: SQLiteWALSnapshotTarget, case: bytes = b""):
    return target.as_command_target().execute(
        case,
        timeout_seconds=2.0,
        max_output_bytes=4096,
        max_total_output_bytes=8192,
    )


def test_long_lived_wal_reader_retains_snapshot_across_writer_commit() -> None:
    result = _execute(SQLiteWALSnapshotTarget())

    assert result.infrastructure_error is None
    assert result.exit_code == 0
    assert result.stderr.text == ""
    assert json.loads(result.stdout.text) == {
        "journal_mode": "wal",
        "initial_value": 0,
        "writer_committed_value": 1,
        "retained_value": 0,
        "refreshed_value": 1,
    }


def test_wal_snapshot_target_rejects_nonempty_untrusted_input() -> None:
    result = _execute(SQLiteWALSnapshotTarget(), b"SELECT 1")

    assert result.infrastructure_error is None
    assert result.exit_code == 2
    assert result.stdout.text == ""
    assert (
        result.stderr.text.strip()
        == "protocol_error: SQLite WAL snapshot target requires empty input"
    )


def test_real_harness_repeats_wal_reader_snapshot_deterministically() -> None:
    harness = DifferentialHarness(
        candidate=SQLiteWALSnapshotTarget().as_command_target(),
        oracle=SQLiteWALSnapshotTarget().as_command_target(),
    )

    run = harness.evaluate(b"")

    assert run.candidate.exit_code == 0
    assert run.oracle.exit_code == 0
    assert run.comparison.equivalent is True
    assert run.comparison.classification == "match"
