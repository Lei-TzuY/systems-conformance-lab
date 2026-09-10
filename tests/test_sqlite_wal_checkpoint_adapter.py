from __future__ import annotations

import json

from systems_conformance.harness import DifferentialHarness
from systems_conformance.sqlite_wal_checkpoint_adapter import SQLiteWALCheckpointTarget


def _execute(target: SQLiteWALCheckpointTarget, case: bytes = b""):
    return target.as_command_target().execute(
        case,
        timeout_seconds=2.0,
        max_output_bytes=4096,
        max_total_output_bytes=8192,
    )


def test_reader_snapshot_blocks_truncate_checkpoint_until_release() -> None:
    result = _execute(SQLiteWALCheckpointTarget())

    assert result.infrastructure_error is None
    assert result.exit_code == 0, result.stderr.text
    assert result.stderr.text == ""
    payload = json.loads(result.stdout.text)
    assert payload["journal_mode"] == "wal"
    assert payload["reader_snapshot"] == 0
    assert payload["writer_committed_value"] == 3
    assert payload["blocked_checkpoint"]["busy"] == 1
    assert payload["blocked_checkpoint"]["log_frames"] >= 0
    assert payload["blocked_checkpoint"]["checkpointed_frames"] >= 0
    assert payload["released_checkpoint"]["busy"] == 0
    assert payload["released_checkpoint"]["log_frames"] >= 0
    assert payload["released_checkpoint"]["checkpointed_frames"] >= 0
    assert payload["fresh_value"] == 3


def test_wal_checkpoint_target_rejects_nonempty_untrusted_input() -> None:
    result = _execute(SQLiteWALCheckpointTarget(), b"PRAGMA wal_checkpoint(TRUNCATE)")

    assert result.infrastructure_error is None
    assert result.exit_code == 2
    assert result.stdout.text == ""
    assert (
        result.stderr.text.strip()
        == "protocol_error: SQLite WAL checkpoint target requires empty input"
    )


def test_real_harness_repeats_wal_checkpoint_contention_deterministically() -> None:
    harness = DifferentialHarness(
        candidate=SQLiteWALCheckpointTarget().as_command_target(),
        oracle=SQLiteWALCheckpointTarget().as_command_target(),
    )

    run = harness.evaluate(b"")

    assert run.candidate.exit_code == 0, run.candidate.stderr.text
    assert run.oracle.exit_code == 0, run.oracle.stderr.text
    assert run.comparison.equivalent is True
    assert run.comparison.classification == "match"
