from __future__ import annotations

import json

import pytest

from systems_conformance.harness import DifferentialHarness
from systems_conformance.sqlite_reader_contention_adapter import SQLiteReaderContentionTarget


def _execute(target: SQLiteReaderContentionTarget, case: bytes = b""):
    return target.as_command_target().execute(
        case,
        timeout_seconds=2.0,
        max_output_bytes=4096,
        max_total_output_bytes=8192,
    )


def test_delete_exclusive_writer_blocks_reader_until_commit() -> None:
    result = _execute(SQLiteReaderContentionTarget(journal_mode="delete"))

    assert result.infrastructure_error is None
    assert result.exit_code == 0
    assert result.stderr.text == ""
    assert json.loads(result.stdout.text) == {
        "journal_mode": "delete",
        "reader_blocked": True,
        "reader_error": "SQLITE_BUSY",
        "precommit_value": None,
        "postcommit_value": 1,
    }


def test_wal_exclusive_writer_preserves_committed_reader_snapshot() -> None:
    result = _execute(SQLiteReaderContentionTarget(journal_mode="wal"))

    assert result.infrastructure_error is None
    assert result.exit_code == 0
    assert result.stderr.text == ""
    assert json.loads(result.stdout.text) == {
        "journal_mode": "wal",
        "reader_blocked": False,
        "reader_error": None,
        "precommit_value": 0,
        "postcommit_value": 1,
    }


def test_reader_contention_target_rejects_nonempty_untrusted_input() -> None:
    result = _execute(SQLiteReaderContentionTarget(), b"SELECT 1")

    assert result.infrastructure_error is None
    assert result.exit_code == 2
    assert result.stdout.text == ""
    assert (
        result.stderr.text.strip()
        == "protocol_error: SQLite reader contention target requires empty input"
    )


def test_reader_contention_target_rejects_invalid_configuration_before_spawn() -> None:
    with pytest.raises(ValueError, match="journal_mode"):
        SQLiteReaderContentionTarget(journal_mode="memory")  # type: ignore[arg-type]


def test_real_harness_repeats_wal_snapshot_transcript_deterministically() -> None:
    harness = DifferentialHarness(
        candidate=SQLiteReaderContentionTarget(journal_mode="wal").as_command_target(),
        oracle=SQLiteReaderContentionTarget(journal_mode="wal").as_command_target(),
    )

    run = harness.evaluate(b"")

    assert run.candidate.exit_code == 0
    assert run.oracle.exit_code == 0
    assert run.comparison.equivalent is True
    assert run.comparison.classification == "match"
