from __future__ import annotations

import json

from systems_conformance import (
    DifferentialHarness,
    FailureSignature,
    FuzzFailure,
    SQLiteQueryTarget,
)
from systems_conformance.sqlite_query_triage import reduce_sqlite_query_failure_to_repro


def _case() -> bytes:
    payload = {
        "setup": [
            "CREATE TABLE items(v INTEGER)",
            "CREATE TABLE noise(v INTEGER)",
        ],
        "query": "SELECT ? AS value",
        "params": [987654],
        "fault": {"operation": "setup", "occurrence": 1, "kind": "abort"},
    }
    return json.dumps(payload, separators=(",", ":")).encode()


def test_real_sqlite_query_failure_reduces_across_all_phases_and_replays(tmp_path) -> None:
    candidate = SQLiteQueryTarget(enable_faults=True).as_command_target()
    oracle = SQLiteQueryTarget(enable_faults=False).as_command_target()
    harness = DifferentialHarness(candidate=candidate, oracle=oracle, timeout_seconds=2.0)
    initial = _case()
    run = harness.evaluate(initial)

    assert run.signature is not None
    assert run.comparison.classification == "product_mismatch"
    failure = FuzzFailure(
        evaluation_index=0,
        case=initial,
        comparison=run.comparison,
        signature=run.signature,
    )

    result = reduce_sqlite_query_failure_to_repro(
        failure,
        harness=harness,
        destination=tmp_path / "repro",
        max_evaluations_per_phase=64,
        metadata={"source": "sqlite-query-multiphase-triage"},
    )
    reduced = json.loads(result.reduced)

    assert result.fault_reduction.accepted_steps > 0
    assert result.setup_reduction.accepted_steps > 0
    assert result.parameter_reduction.accepted_steps > 0
    assert reduced["fault"] == {"operation": "setup", "occurrence": 0, "kind": "abort"}
    assert len(reduced["setup"]) == 1
    assert reduced["params"] == [None]
    assert result.repro.input_path.read_bytes() == result.reduced

    rerun = harness.evaluate(result.reduced)
    assert rerun.signature == failure.signature
    assert rerun.comparison.classification == "product_mismatch"

    replay = harness.replay_repro(result.repro.path)
    assert replay.reproduced is True
    assert replay.run.signature == failure.signature


def test_query_triage_rejects_inconsistent_failure_signature(tmp_path) -> None:
    candidate = SQLiteQueryTarget(enable_faults=True).as_command_target()
    oracle = SQLiteQueryTarget(enable_faults=False).as_command_target()
    harness = DifferentialHarness(candidate=candidate, oracle=oracle, timeout_seconds=2.0)
    initial = _case()
    run = harness.evaluate(initial)

    assert run.signature is not None
    inconsistent = FuzzFailure(
        evaluation_index=0,
        case=initial,
        comparison=run.comparison,
        signature=FailureSignature(kind="product_mismatch", dimensions=("timeout",)),
    )

    try:
        reduce_sqlite_query_failure_to_repro(
            inconsistent,
            harness=harness,
            destination=tmp_path / "repro",
            max_evaluations_per_phase=8,
        )
    except ValueError as exc:
        assert str(exc) == "fuzz failure carries an inconsistent stable signature"
    else:
        raise AssertionError("expected inconsistent failure signature rejection")
