from __future__ import annotations

import json

import pytest

from systems_conformance import SQLiteQueryTarget, SQLiteTransactionTarget


@pytest.mark.parametrize("field", ["foreign_keys", "enable_faults"])
@pytest.mark.parametrize("value", [0, 1, "true", None])
def test_query_target_rejects_non_boolean_execution_flags(field: str, value: object) -> None:
    with pytest.raises(TypeError, match=rf"{field} must be a bool"):
        SQLiteQueryTarget(**{field: value})  # type: ignore[arg-type]


@pytest.mark.parametrize("field", ["foreign_keys", "enable_faults", "reopen_before_observe"])
@pytest.mark.parametrize("value", [0, 1, "true", None])
def test_transaction_target_rejects_non_boolean_execution_flags(
    field: str, value: object
) -> None:
    with pytest.raises(TypeError, match=rf"{field} must be a bool"):
        SQLiteTransactionTarget(**{field: value})  # type: ignore[arg-type]


def test_valid_query_flags_execute_real_sqlite_worker() -> None:
    request = json.dumps(
        {"setup": [], "query": "PRAGMA foreign_keys", "params": []},
        separators=(",", ":"),
    ).encode()

    disabled = SQLiteQueryTarget(foreign_keys=False, enable_faults=False)
    result = disabled.as_command_target().execute(
        request,
        timeout_seconds=2.0,
        max_output_bytes=4096,
        max_total_output_bytes=8192,
    )

    assert result.infrastructure_error is None
    assert result.exit_code == 0
    assert json.loads(result.stdout.text)["rows"] == [[0]]


def test_valid_transaction_flags_execute_real_sqlite_worker() -> None:
    request = json.dumps(
        {
            "setup": [],
            "transaction": [{"sql": "SELECT 1", "params": []}],
            "observe": {"sql": "PRAGMA foreign_keys", "params": []},
        },
        separators=(",", ":"),
    ).encode()

    disabled = SQLiteTransactionTarget(
        foreign_keys=False,
        enable_faults=False,
        reopen_before_observe=False,
    )
    result = disabled.as_command_target().execute(
        request,
        timeout_seconds=2.0,
        max_output_bytes=4096,
        max_total_output_bytes=8192,
    )

    assert result.infrastructure_error is None
    assert result.exit_code == 0
    assert json.loads(result.stdout.text)["observation"]["rows"] == [[0]]
