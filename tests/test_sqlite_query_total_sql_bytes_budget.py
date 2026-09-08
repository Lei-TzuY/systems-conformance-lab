from __future__ import annotations

import json

import pytest

from systems_conformance import DifferentialHarness
from systems_conformance.sqlite_adapter import SQLiteQueryTarget

_SETUP_CREATE = "CREATE TABLE t(x)"
_SETUP_INSERT = "INSERT INTO t VALUES (1)"
_QUERY = "SELECT x FROM t"
_TOTAL_SQL_BYTES = sum(
    len(sql.encode("utf-8")) for sql in (_SETUP_CREATE, _SETUP_INSERT, _QUERY)
)


def _request() -> bytes:
    return json.dumps(
        {
            "setup": [_SETUP_CREATE, _SETUP_INSERT],
            "query": _QUERY,
            "params": [],
        },
        separators=(",", ":"),
    ).encode("utf-8")


def _execute(max_total_sql_bytes: int):
    return SQLiteQueryTarget(max_total_sql_bytes=max_total_sql_bytes).as_command_target().execute(
        _request(),
        timeout_seconds=2.0,
        max_output_bytes=4096,
        max_total_output_bytes=8192,
    )


def test_sqlite_query_total_sql_bytes_budget_allows_exact_boundary() -> None:
    result = _execute(_TOTAL_SQL_BYTES)

    assert result.infrastructure_error is None
    assert result.exit_code == 0
    assert json.loads(result.stdout.text) == {"columns": ["x"], "rows": [[1]]}


def test_sqlite_query_total_sql_bytes_budget_rejects_before_execution() -> None:
    result = _execute(_TOTAL_SQL_BYTES - 1)

    assert result.infrastructure_error is None
    assert result.exit_code == 2
    assert result.stdout.text == ""
    assert result.stderr.text.strip() == (
        "protocol_error: request SQL exceeds max_total_sql_bytes: "
        f"{_TOTAL_SQL_BYTES - 1}"
    )


@pytest.mark.parametrize("max_total_sql_bytes", [0, -1, True, 1.5, "10"])
def test_sqlite_query_target_rejects_invalid_total_sql_byte_budgets(
    max_total_sql_bytes: object,
) -> None:
    with pytest.raises(
        ValueError, match="max_total_sql_bytes must be a positive integer"
    ):
        SQLiteQueryTarget(  # type: ignore[arg-type]
            max_total_sql_bytes=max_total_sql_bytes
        )


def test_sqlite_query_total_sql_bytes_budget_changes_replay_context() -> None:
    candidate = SQLiteQueryTarget(
        max_total_sql_bytes=_TOTAL_SQL_BYTES - 1
    ).as_command_target()
    oracle = SQLiteQueryTarget(max_total_sql_bytes=_TOTAL_SQL_BYTES).as_command_target()
    candidate_harness = DifferentialHarness(candidate=candidate, oracle=candidate)
    oracle_harness = DifferentialHarness(candidate=oracle, oracle=oracle)

    assert candidate_harness.replay_context_sha256 != oracle_harness.replay_context_sha256


def test_real_differential_harness_observes_query_total_sql_bytes_budget() -> None:
    candidate = SQLiteQueryTarget(
        max_total_sql_bytes=_TOTAL_SQL_BYTES - 1
    ).as_command_target()
    oracle = SQLiteQueryTarget(max_total_sql_bytes=_TOTAL_SQL_BYTES).as_command_target()
    harness = DifferentialHarness(candidate=candidate, oracle=oracle, timeout_seconds=2.0)

    run = harness.evaluate(_request())

    assert run.candidate.infrastructure_error is None
    assert run.oracle.infrastructure_error is None
    assert run.candidate.exit_code == 2
    assert run.candidate.stderr.text.strip() == (
        "protocol_error: request SQL exceeds max_total_sql_bytes: "
        f"{_TOTAL_SQL_BYTES - 1}"
    )
    assert run.oracle.exit_code == 0
    assert json.loads(run.oracle.stdout.text) == {"columns": ["x"], "rows": [[1]]}
    assert run.comparison.classification == "product_mismatch"
    assert run.signature is not None
    assert run.signature.kind == "product_mismatch"
