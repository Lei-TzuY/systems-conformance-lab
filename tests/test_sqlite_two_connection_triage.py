from __future__ import annotations

import json

import pytest

from systems_conformance import (
    CandidateBudgetExhausted,
    DifferentialHarness,
    FailureSignature,
    FuzzFailure,
    SQLiteTwoConnectionScenarioTarget,
    reduce_sqlite_two_connection_failure_to_repro,
)


def _case() -> bytes:
    payload = {
        "setup": [
            "CREATE TABLE items(v INTEGER NOT NULL)",
            "INSERT INTO items VALUES (0)",
            "CREATE TABLE noise(v INTEGER)",
        ],
        "steps": [
            {"connection": "a", "op": "query", "sql": "SELECT 111 AS noise"},
            {"connection": "a", "op": "begin", "mode": "exclusive"},
            {
                "connection": "b",
                "op": "try_query",
                "sql": "SELECT v FROM items WHERE v >= ?",
                "params": [-987654],
            },
            {"connection": "a", "op": "rollback"},
            {
                "connection": "b",
                "op": "query",
                "sql": "SELECT ? AS tail",
                "params": [999],
            },
        ],
    }
    return json.dumps(payload, separators=(",", ":")).encode()


def _failure_and_harness() -> tuple[FuzzFailure[bytes], DifferentialHarness]:
    harness = DifferentialHarness(
        candidate=SQLiteTwoConnectionScenarioTarget(journal_mode="delete").as_command_target(),
        oracle=SQLiteTwoConnectionScenarioTarget(journal_mode="wal").as_command_target(),
        timeout_seconds=5.0,
    )
    initial = _case()
    run = harness.evaluate(initial)
    assert run.signature is not None
    assert run.comparison.classification == "product_mismatch"
    return (
        FuzzFailure(
            evaluation_index=0,
            case=initial,
            comparison=run.comparison,
            signature=run.signature,
        ),
        harness,
    )


def test_real_two_connection_failure_reduces_across_all_phases_and_replays(
    tmp_path,
) -> None:
    failure, harness = _failure_and_harness()

    result = reduce_sqlite_two_connection_failure_to_repro(
        failure,
        harness=harness,
        destination=tmp_path / "repro",
        max_evaluations_per_phase=64,
        metadata={"source": "sqlite-two-connection-multiphase-triage"},
    )
    reduced = json.loads(result.reduced)

    assert result.step_reduction.accepted_steps > 0
    assert result.setup_reduction.accepted_steps > 0
    assert result.parameter_reduction.accepted_steps > 0
    assert reduced["setup"] == ["CREATE TABLE items(v INTEGER NOT NULL)"]
    assert reduced["steps"] == [
        {"connection": "a", "mode": "exclusive", "op": "begin"},
        {
            "connection": "b",
            "op": "try_query",
            "params": [None],
            "sql": "SELECT v FROM items WHERE v >= ?",
        },
        {"connection": "a", "op": "rollback"},
    ]
    assert result.repro.input_path.read_bytes() == result.reduced

    rerun = harness.evaluate(result.reduced)
    assert rerun.signature == failure.signature
    assert rerun.comparison.classification == "product_mismatch"

    replay = harness.replay_repro(result.repro.path)
    assert replay.reproduced is True
    assert replay.run.signature == failure.signature


def test_two_connection_triage_fails_closed_on_structural_budget(tmp_path) -> None:
    failure, harness = _failure_and_harness()
    destination = tmp_path / "repro"

    with pytest.raises(CandidateBudgetExhausted) as exc_info:
        reduce_sqlite_two_connection_failure_to_repro(
            failure,
            harness=harness,
            destination=destination,
            max_evaluations_per_phase=64,
            max_candidate_visits_per_phase=1,
        )

    assert exc_info.value.candidate_visits == 1
    assert exc_info.value.max_candidate_visits == 1
    assert not destination.exists()


def test_two_connection_triage_rejects_inconsistent_failure_signature(tmp_path) -> None:
    failure, harness = _failure_and_harness()
    inconsistent = FuzzFailure(
        evaluation_index=failure.evaluation_index,
        case=failure.case,
        comparison=failure.comparison,
        signature=FailureSignature(kind="product_mismatch", dimensions=("exit_code",)),
    )

    with pytest.raises(ValueError, match="inconsistent stable signature"):
        reduce_sqlite_two_connection_failure_to_repro(
            inconsistent,
            harness=harness,
            destination=tmp_path / "repro",
            max_evaluations_per_phase=8,
        )
