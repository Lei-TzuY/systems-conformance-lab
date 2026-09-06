from __future__ import annotations

import json

import pytest

from systems_conformance import DifferentialHarness, SQLiteTransactionTarget, reduce_case
from systems_conformance.sqlite_transaction_reducer import (
    sqlite_transaction_fault_occurrence_complexity,
    sqlite_transaction_fault_occurrence_reductions,
    sqlite_transaction_parameter_complexity,
    sqlite_transaction_parameter_reductions,
    sqlite_transaction_statement_count,
    sqlite_transaction_statement_deletions,
)


def _statement(sql: str, params: list[object] | None = None) -> dict[str, object]:
    return {"sql": sql, "params": [] if params is None else params}


def _case(
    *,
    setup: list[str],
    transaction: list[dict[str, object]],
    observe: dict[str, object] | None = None,
    fault: dict[str, object] | None = None,
) -> bytes:
    payload: dict[str, object] = {
        "setup": setup,
        "transaction": transaction,
        "observe": observe or _statement("SELECT v FROM items ORDER BY v"),
    }
    if fault is not None:
        payload["fault"] = fault
    return json.dumps(payload, separators=(",", ":")).encode()


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


def test_parameter_reductions_are_deterministic_and_strictly_simpler() -> None:
    case = _case(
        setup=["CREATE TABLE items(v INTEGER)"],
        transaction=[_statement("INSERT INTO items VALUES (?)", [42])],
        observe=_statement("SELECT v FROM items WHERE v = ?", ["42"]),
    )

    first = list(sqlite_transaction_parameter_reductions(case))
    second = list(sqlite_transaction_parameter_reductions(case))
    original_complexity = sqlite_transaction_parameter_complexity(case)

    assert first == second
    assert first
    assert all(
        sqlite_transaction_parameter_complexity(candidate) < original_complexity
        for candidate in first
    )
    decoded = [json.loads(candidate) for candidate in first]
    assert decoded[0]["transaction"][0]["params"] == [0]
    assert any(candidate["observe"]["params"] == [""] for candidate in decoded)
    assert all(candidate["setup"] == ["CREATE TABLE items(v INTEGER)"] for candidate in decoded)


def test_parameter_reducer_rejects_non_scalar_params() -> None:
    case = _case(
        setup=[],
        transaction=[_statement("SELECT ?", [[1]])],
        observe=_statement("SELECT 1"),
    )

    with pytest.raises(TypeError, match="JSON scalar"):
        sqlite_transaction_parameter_complexity(case)


def test_fault_occurrence_reductions_are_deterministic_and_strictly_lower() -> None:
    case = _case(
        setup=["CREATE TABLE items(v INTEGER)"],
        transaction=[_statement("INSERT INTO items VALUES (1)")],
        fault={"operation": "transaction", "occurrence": 9, "kind": "abort"},
    )

    first = list(sqlite_transaction_fault_occurrence_reductions(case))
    second = list(sqlite_transaction_fault_occurrence_reductions(case))

    assert first == second
    assert [json.loads(candidate)["fault"]["occurrence"] for candidate in first] == [0, 1, 2]
    assert all(sqlite_transaction_fault_occurrence_complexity(candidate) < 9 for candidate in first)
    for candidate in first:
        decoded = json.loads(candidate)
        assert decoded["fault"]["operation"] == "transaction"
        assert decoded["fault"]["kind"] == "abort"
        assert decoded["transaction"] == [_statement("INSERT INTO items VALUES (1)")]


def test_fault_occurrence_reducer_handles_absent_and_invalid_faults() -> None:
    no_fault = _case(setup=[], transaction=[_statement("SELECT 1")], observe=_statement("SELECT 1"))
    assert sqlite_transaction_fault_occurrence_complexity(no_fault) == 0
    assert list(sqlite_transaction_fault_occurrence_reductions(no_fault)) == []

    invalid = _case(
        setup=[],
        transaction=[_statement("SELECT 1")],
        observe=_statement("SELECT 1"),
        fault={"operation": "transaction", "occurrence": True, "kind": "abort"},
    )
    with pytest.raises(ValueError, match="non-negative integer"):
        sqlite_transaction_fault_occurrence_complexity(invalid)


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


def test_real_commit_rollback_failure_reduces_transaction_scalar() -> None:
    candidate = SQLiteTransactionTarget(finalize="commit").as_command_target()
    oracle = SQLiteTransactionTarget(finalize="rollback").as_command_target()
    harness = DifferentialHarness(candidate=candidate, oracle=oracle, timeout_seconds=2.0)
    initial = _case(
        setup=["CREATE TABLE items(v INTEGER)"],
        transaction=[_statement("INSERT INTO items VALUES (?)", [987654])],
        observe=_statement("SELECT COUNT(*) AS count FROM items"),
    )
    initial_run = harness.evaluate(initial)
    assert initial_run.signature is not None
    signature = initial_run.signature

    reduction = reduce_case(
        initial,
        candidates=sqlite_transaction_parameter_reductions,
        preserves_failure=lambda case: harness.preserves_failure(case, signature),
        measure=sqlite_transaction_parameter_complexity,
        max_evaluations=32,
    )
    reduced = json.loads(reduction.reduced)
    rerun = harness.evaluate(reduction.reduced)

    assert rerun.signature == signature
    assert rerun.comparison.classification == "product_mismatch"
    assert reduced["transaction"][0]["params"] == [None]
    assert sqlite_transaction_parameter_complexity(reduction.reduced) == 0
    assert reduction.accepted_steps > 0


def test_real_fault_failure_reduces_occurrence_and_preserves_signature() -> None:
    candidate = SQLiteTransactionTarget(enable_faults=True).as_command_target()
    oracle = SQLiteTransactionTarget(enable_faults=False).as_command_target()
    harness = DifferentialHarness(candidate=candidate, oracle=oracle, timeout_seconds=2.0)
    initial = _case(
        setup=["CREATE TABLE items(v INTEGER)"],
        transaction=[
            _statement("INSERT INTO items VALUES (1)"),
            _statement("INSERT INTO items VALUES (2)"),
            _statement("INSERT INTO items VALUES (3)"),
        ],
        observe=_statement("SELECT COUNT(*) AS count FROM items"),
        fault={"operation": "transaction", "occurrence": 2, "kind": "abort"},
    )
    initial_run = harness.evaluate(initial)
    assert initial_run.signature is not None
    signature = initial_run.signature
    assert initial_run.comparison.classification == "product_mismatch"

    reduction = reduce_case(
        initial,
        candidates=sqlite_transaction_fault_occurrence_reductions,
        preserves_failure=lambda case: harness.preserves_failure(case, signature),
        measure=sqlite_transaction_fault_occurrence_complexity,
        max_evaluations=8,
    )
    reduced = json.loads(reduction.reduced)
    rerun = harness.evaluate(reduction.reduced)

    assert rerun.signature == signature
    assert rerun.comparison.classification == "product_mismatch"
    assert reduced["fault"] == {"operation": "transaction", "occurrence": 0, "kind": "abort"}
    assert sqlite_transaction_fault_occurrence_complexity(reduction.reduced) == 0
    assert reduction.accepted_steps > 0
