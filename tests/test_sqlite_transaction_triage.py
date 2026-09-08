from __future__ import annotations

import json

from systems_conformance import DifferentialHarness, FuzzFailure, SQLiteTransactionTarget
from systems_conformance.sqlite_transaction_triage import (
    reduce_sqlite_transaction_failure_to_repro,
)


def _statement(sql: str, params: list[object] | None = None) -> dict[str, object]:
    return {"sql": sql, "params": [] if params is None else params}


def _case() -> bytes:
    payload = {
        "setup": [
            "CREATE TABLE items(v INTEGER)",
            "CREATE TABLE noise(v INTEGER)",
        ],
        "transaction": [
            _statement("SELECT ?", [987654]),
            _statement("SELECT ?", [222]),
            _statement("SELECT ?", [333]),
        ],
        "observe": _statement("SELECT COUNT(*) AS count FROM items"),
        "fault": {"operation": "transaction", "occurrence": 2, "kind": "abort"},
    }
    return json.dumps(payload, separators=(",", ":")).encode()


def test_real_sqlite_transaction_failure_reduces_across_all_phases_and_replays(tmp_path) -> None:
    candidate = SQLiteTransactionTarget(enable_faults=True).as_command_target()
    oracle = SQLiteTransactionTarget(enable_faults=False).as_command_target()
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

    result = reduce_sqlite_transaction_failure_to_repro(
        failure,
        harness=harness,
        destination=tmp_path / "repro",
        max_evaluations_per_phase=64,
        metadata={"source": "sqlite-transaction-multiphase-triage"},
    )
    reduced = json.loads(result.reduced)

    assert result.fault_reduction.accepted_steps > 0
    assert result.statement_reduction.accepted_steps > 0
    assert result.parameter_reduction.accepted_steps > 0
    assert reduced["fault"] == {"operation": "transaction", "occurrence": 0, "kind": "abort"}
    assert reduced["setup"] == ["CREATE TABLE items(v INTEGER)"]
    assert len(reduced["transaction"]) == 1
    assert reduced["transaction"][0]["params"] == [None]
    assert result.repro.input_path.read_bytes() == result.reduced

    rerun = harness.evaluate(result.reduced)
    assert rerun.signature == failure.signature
    assert rerun.comparison.classification == "product_mismatch"

    replay = harness.replay_repro(result.repro.path)
    assert replay.reproduced is True
    assert replay.run.signature == failure.signature
