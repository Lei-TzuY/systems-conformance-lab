from __future__ import annotations

import json

import pytest

from systems_conformance.harness import DifferentialHarness
from systems_conformance.sqlite_lock_adapter import SQLiteLockContentionTarget


def _execute(target: SQLiteLockContentionTarget, case: bytes = b""):
    return target.as_command_target().execute(
        case,
        timeout_seconds=2.0,
        max_output_bytes=4096,
        max_total_output_bytes=8192,
    )


@pytest.mark.parametrize("journal_mode", ["delete", "wal"])
def test_real_sqlite_writer_contention_blocks_then_recovers(journal_mode: str) -> None:
    result = _execute(SQLiteLockContentionTarget(journal_mode=journal_mode))

    assert result.infrastructure_error is None
    assert result.exit_code == 0
    assert result.stderr.text == ""
    assert json.loads(result.stdout.text) == {
        "blocked": True,
        "blocked_error": "SQLITE_BUSY",
        "retry_acquired": True,
        "rows": [2],
    }


def test_lock_target_rejects_nonempty_untrusted_input() -> None:
    result = _execute(SQLiteLockContentionTarget(), b"SELECT 1")

    assert result.infrastructure_error is None
    assert result.exit_code == 2
    assert result.stdout.text == ""
    assert result.stderr.text.strip() == "protocol_error: SQLite lock target requires empty input"


def test_lock_target_rejects_invalid_configuration_before_spawn() -> None:
    with pytest.raises(ValueError, match="holder_begin"):
        SQLiteLockContentionTarget(holder_begin="deferred")  # type: ignore[arg-type]


def test_real_harness_compares_delete_and_wal_writer_lock_semantics() -> None:
    harness = DifferentialHarness(
        candidate=SQLiteLockContentionTarget(journal_mode="wal").as_command_target(),
        oracle=SQLiteLockContentionTarget(journal_mode="delete").as_command_target(),
    )

    run = harness.evaluate(b"")

    assert run.comparison.equal
    assert run.comparison.classification == "equal"
