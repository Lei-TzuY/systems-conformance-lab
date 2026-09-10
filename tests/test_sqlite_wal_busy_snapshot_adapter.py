from __future__ import annotations

import json
import sqlite3

from systems_conformance.harness import DifferentialHarness
from systems_conformance.sqlite_wal_busy_snapshot_adapter import (
    SQLiteWALBusySnapshotTarget,
)


def _execute(target: SQLiteWALBusySnapshotTarget, case: bytes = b""):
    return target.as_command_target().execute(
        case,
        timeout_seconds=2.0,
        max_output_bytes=4096,
        max_total_output_bytes=8192,
    )


def test_stale_wal_reader_upgrade_reports_busy_snapshot() -> None:
    result = _execute(SQLiteWALBusySnapshotTarget())

    assert result.infrastructure_error is None
    assert result.exit_code == 0, result.stderr.text
    assert result.stderr.text == ""
    assert json.loads(result.stdout.text) == {
        "journal_mode": "wal",
        "initial_value": 0,
        "writer_committed_value": 1,
        "upgrade_error_code": sqlite3.SQLITE_BUSY_SNAPSHOT,
        "retained_value": 0,
        "refreshed_value": 1,
    }


def test_wal_busy_snapshot_target_rejects_nonempty_untrusted_input() -> None:
    result = _execute(SQLiteWALBusySnapshotTarget(), b"UPDATE items SET v = 9")

    assert result.infrastructure_error is None
    assert result.exit_code == 2
    assert result.stdout.text == ""
    assert (
        result.stderr.text.strip()
        == "protocol_error: SQLite WAL busy-snapshot target requires empty input"
    )


def test_real_harness_repeats_wal_busy_snapshot_deterministically() -> None:
    harness = DifferentialHarness(
        candidate=SQLiteWALBusySnapshotTarget().as_command_target(),
        oracle=SQLiteWALBusySnapshotTarget().as_command_target(),
    )

    run = harness.evaluate(b"")

    assert run.candidate.exit_code == 0, run.candidate.stderr.text
    assert run.oracle.exit_code == 0, run.oracle.stderr.text
    assert run.comparison.equivalent is True
    assert run.comparison.classification == "match"
