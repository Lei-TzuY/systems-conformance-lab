from __future__ import annotations

import json

import pytest

from systems_conformance import (
    DifferentialHarness,
    SQLiteTwoConnectionScenarioTarget,
)


def _case(*, setup: list[str], steps: list[dict[str, object]]) -> bytes:
    return json.dumps(
        {"setup": setup, "steps": steps},
        separators=(",", ":"),
    ).encode()


def _execute(target: SQLiteTwoConnectionScenarioTarget, case: bytes):
    return target.as_command_target().execute(
        case,
        timeout_seconds=5.0,
        max_output_bytes=64 * 1024,
        max_total_output_bytes=128 * 1024,
    )


def _writer_contention_case() -> bytes:
    return _case(
        setup=["CREATE TABLE items(v INTEGER NOT NULL)"],
        steps=[
            {"connection": "a", "op": "begin", "mode": "immediate"},
            {"connection": "a", "op": "execute", "sql": "INSERT INTO items VALUES (1)"},
            {"connection": "b", "op": "try_begin", "mode": "immediate"},
            {"connection": "a", "op": "rollback"},
            {"connection": "b", "op": "begin", "mode": "immediate"},
            {"connection": "b", "op": "execute", "sql": "INSERT INTO items VALUES (2)"},
            {"connection": "b", "op": "commit"},
            {
                "connection": "b",
                "op": "query",
                "sql": "SELECT v FROM items ORDER BY v",
            },
        ],
    )


def test_wal_snapshot_visibility_runs_through_data_driven_scenario() -> None:
    case = _case(
        setup=[
            "CREATE TABLE items(v INTEGER NOT NULL)",
            "INSERT INTO items VALUES (0)",
        ],
        steps=[
            {"connection": "a", "op": "begin", "mode": "deferred"},
            {"connection": "a", "op": "query", "sql": "SELECT v FROM items"},
            {"connection": "b", "op": "begin", "mode": "immediate"},
            {"connection": "b", "op": "execute", "sql": "UPDATE items SET v = 1"},
            {"connection": "b", "op": "commit"},
            {"connection": "a", "op": "query", "sql": "SELECT v FROM items"},
            {"connection": "a", "op": "commit"},
            {"connection": "a", "op": "query", "sql": "SELECT v FROM items"},
        ],
    )

    result = _execute(SQLiteTwoConnectionScenarioTarget(journal_mode="wal"), case)

    assert result.infrastructure_error is None
    assert result.exit_code == 0, result.stderr.text
    assert json.loads(result.stdout.text) == {
        "steps": [
            {"connection": "a", "op": "begin", "mode": "deferred"},
            {"connection": "a", "op": "query", "columns": ["v"], "rows": [[0]]},
            {"connection": "b", "op": "begin", "mode": "immediate"},
            {"connection": "b", "op": "execute"},
            {"connection": "b", "op": "commit"},
            {"connection": "a", "op": "query", "columns": ["v"], "rows": [[0]]},
            {"connection": "a", "op": "commit"},
            {"connection": "a", "op": "query", "columns": ["v"], "rows": [[1]]},
        ]
    }


@pytest.mark.parametrize("journal_mode", ["delete", "wal"])
def test_writer_contention_and_recovery_runs_through_scenario(journal_mode: str) -> None:
    result = _execute(
        SQLiteTwoConnectionScenarioTarget(journal_mode=journal_mode),  # type: ignore[arg-type]
        _writer_contention_case(),
    )

    assert result.infrastructure_error is None
    assert result.exit_code == 0, result.stderr.text
    assert json.loads(result.stdout.text) == {
        "steps": [
            {"connection": "a", "op": "begin", "mode": "immediate"},
            {"connection": "a", "op": "execute"},
            {
                "connection": "b",
                "op": "try_begin",
                "mode": "immediate",
                "ok": False,
                "error": "SQLITE_BUSY",
            },
            {"connection": "a", "op": "rollback"},
            {"connection": "b", "op": "begin", "mode": "immediate"},
            {"connection": "b", "op": "execute"},
            {"connection": "b", "op": "commit"},
            {"connection": "b", "op": "query", "columns": ["v"], "rows": [[2]]},
        ]
    }


def test_differential_harness_compares_writer_exclusion_across_journal_modes() -> None:
    harness = DifferentialHarness(
        candidate=SQLiteTwoConnectionScenarioTarget(journal_mode="wal").as_command_target(),
        oracle=SQLiteTwoConnectionScenarioTarget(journal_mode="delete").as_command_target(),
        timeout_seconds=5.0,
    )

    run = harness.evaluate(_writer_contention_case())

    assert run.candidate.exit_code == 0
    assert run.oracle.exit_code == 0
    assert run.comparison.classification == "match"
    assert run.signature is None


def test_transaction_control_in_input_sql_is_rejected_before_execution() -> None:
    case = _case(
        setup=[],
        steps=[{"connection": "a", "op": "execute", "sql": "/*x*/ BEGIN IMMEDIATE"}],
    )

    result = _execute(SQLiteTwoConnectionScenarioTarget(), case)

    assert result.infrastructure_error is None
    assert result.exit_code == 2
    assert result.stdout.text == ""
    assert result.stderr.text.strip() == (
        "protocol_error: step 0 sql uses disallowed SQL control: begin"
    )


def test_step_budget_is_enforced_before_database_execution() -> None:
    case = _case(
        setup=[],
        steps=[
            {"connection": "a", "op": "query", "sql": "SELECT 1"},
            {"connection": "b", "op": "query", "sql": "SELECT 2"},
        ],
    )

    result = _execute(SQLiteTwoConnectionScenarioTarget(max_steps=1), case)

    assert result.infrastructure_error is None
    assert result.exit_code == 2
    assert result.stderr.text.strip() == "protocol_error: steps exceeds max_steps: 1"


def test_result_row_budget_fails_closed() -> None:
    case = _case(
        setup=[
            "CREATE TABLE items(v INTEGER NOT NULL)",
            "INSERT INTO items VALUES (1)",
            "INSERT INTO items VALUES (2)",
        ],
        steps=[
            {
                "connection": "a",
                "op": "query",
                "sql": "SELECT v FROM items ORDER BY v",
            }
        ],
    )

    result = _execute(SQLiteTwoConnectionScenarioTarget(max_result_rows=1), case)

    assert result.infrastructure_error is None
    assert result.exit_code == 4
    assert result.stdout.text == ""
    assert result.stderr.text.strip() == "result_error: result exceeds max_result_rows: 1"


def test_empty_query_still_enforces_result_byte_budget() -> None:
    case = _case(
        setup=[],
        steps=[{"connection": "a", "op": "query", "sql": "SELECT 1 AS oversized WHERE 0"}],
    )

    result = _execute(SQLiteTwoConnectionScenarioTarget(max_result_bytes=8), case)

    assert result.infrastructure_error is None
    assert result.exit_code == 4
    assert result.stdout.text == ""
    assert result.stderr.text.strip() == "result_error: result exceeds max_result_bytes: 8"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("max_steps", 0),
        ("max_sql_bytes", True),
        ("max_transcript_bytes", -1),
    ],
)
def test_invalid_budgets_are_rejected_before_spawn(field: str, value: object) -> None:
    kwargs = {field: value}
    with pytest.raises(ValueError, match=f"{field} must be a positive integer"):
        SQLiteTwoConnectionScenarioTarget(**kwargs)  # type: ignore[arg-type]
