from __future__ import annotations

import json

import pytest

from systems_conformance import DifferentialHarness, SQLiteTransactionTarget, reduce_case
from systems_conformance.sqlite_transaction_reducer import (
    sqlite_transaction_statement_count,
    sqlite_transaction_statement_deletions,
)


def _statement(sql: str) -> dict[str, object]:
    return {"sql": sql, "params": []}


def _case(*, setup: list[str], transaction: list[dict[str, object]]) -> bytes:
    return json.dumps(
        {
            "setup": setup,
            "transaction": transaction,
            "observe": _statement("SELECT v FROM items ORDER BY v"),
        },
        separators=(",", ":"),
    ).encode()


def test_statement_deletions_are_deterministic_and_keep_transaction_non_empty() -> None:
    case = _case(
        setup=["CREATE TABLE items(v INTEGER)", "CREATE TABLE noise(v INTEGER)"],
        transaction=[_statement("SELECT 10"), _statement("SELECT 20"), _statement("SELECT 30")],
    )

    first = list(sqlite_transaction_statement_deletions(case))
    second = list(sqlite_transaction_statement_deletions(case))

    assert first == second
    assert first
    assert all(sqlite_transaction_statement_count(candidate) < 5 for candidate in first)
    assert all(json.loads(candidate)["transaction"] for candidate in first)
    assert any(json.loads(candidate)["setup"] == [] for candidate in first)


def test_statement_reducer_rejects_invalid_shape() -> None:
    with pytest.raises(ValueError, match="transaction must be a non-empty list"):
        list(sqlite_transaction_statement_deletions(b'{"setup":[],"transaction":[]}'))


def test_real_commit_rollback_failure_reduces_to_required_statements() -> None:
    candidate = SQLiteTransactionTarget(finalize="commit").as_command_target()
    oracle = SQLiteTransactionTarget(finalize="rollback").as_command_target()
    harness = DifferentialHarness(candidate=candidate, oracle=oracle, timeout_seconds=2.0)
    initial = _case(
        setup=[
            "CREATE TABLE items(v INTEGER)",
            "CREATE TABLE noise(v INTEGER)",
        ],
        transaction=[
            _statement("SELECT 111"),
            _statement("INSERT INTO items VALUES (42)"),
            _statement("SELECT 222"),
        ],
    )
    initial_run = harness.evaluate(initial)
    assert initial_run.signature is not None
    signature = initial_run.signature

    reduction = reduce_case(
        initial,
        candidates=sqlite_transaction_statement_deletions,
        preserves_failure=lambda case: harness.preserves_failure(case, signature),
        measure=sqlite_transaction_statement_count,
        max_evaluations=64,
    )
    reduced = json.loads(reduction.reduced)
    rerun = harness.evaluate(reduction.reduced)

    assert rerun.signature == signature
    assert rerun.comparison.classification == "product_mismatch"
    assert reduced["setup"] == ["CREATE TABLE items(v INTEGER)"]
    assert reduced["transaction"] == [_statement("INSERT INTO items VALUES (42)")]
    assert sqlite_transaction_statement_count(reduction.reduced) == 2
    assert reduction.accepted_steps > 0
