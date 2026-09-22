from __future__ import annotations

import json

import pytest

from systems_conformance import (
    DifferentialHarness,
    SQLiteTwoConnectionScenarioTarget,
    discover_sqlite_two_connection_failure_to_repro,
)


def _case(*, mode: str = "immediate") -> bytes:
    return json.dumps(
        {
            "setup": [
                "CREATE TABLE items(v INTEGER NOT NULL)",
                "INSERT INTO items VALUES (0)",
                "CREATE TABLE noise(v INTEGER)",
            ],
            "steps": [
                {"connection": "a", "op": "query", "sql": "SELECT 111 AS noise"},
                {"connection": "a", "op": "begin", "mode": mode},
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
        },
        separators=(",", ":"),
    ).encode()


def _harness(*, same_journal: bool = False) -> DifferentialHarness:
    return DifferentialHarness(
        candidate=SQLiteTwoConnectionScenarioTarget(journal_mode="delete").as_command_target(),
        oracle=SQLiteTwoConnectionScenarioTarget(
            journal_mode="delete" if same_journal else "wal"
        ).as_command_target(),
        timeout_seconds=5.0,
    )


def test_feedback_discovery_reduces_to_repro_and_replays(tmp_path) -> None:
    harness = _harness()
    result = discover_sqlite_two_connection_failure_to_repro(
        (_case(),),
        harness=harness,
        destination=tmp_path / "repro",
        mutations_per_case=2,
        max_evaluations=4,
        max_corpus_entries=8,
        max_evaluations_per_phase=64,
        metadata={"source": "sqlite-two-connection-discovery-triage"},
    )

    assert result.campaign.evaluations == 3
    assert result.campaign.failures == (result.failure,)
    assert result.failure.comparison.classification == "product_mismatch"
    assert result.failure.signature.kind == "product_mismatch"
    discovered = json.loads(result.failure.case)
    assert discovered["steps"][1]["mode"] == "exclusive"

    assert result.triage.step_reduction.accepted_steps > 0
    assert result.triage.setup_reduction.accepted_steps > 0
    assert result.triage.parameter_reduction.accepted_steps > 0
    reduced = json.loads(result.reduced)
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
    assert result.triage.repro.input_path.read_bytes() == result.reduced

    replay = harness.replay_repro(result.triage.repro.path)
    assert replay.reproduced is True
    assert replay.run.signature == result.failure.signature
    assert replay.bundle.metadata["source"] == "sqlite-two-connection-discovery-triage"


def test_discovery_without_failure_does_not_publish_repro(tmp_path) -> None:
    destination = tmp_path / "repro"

    with pytest.raises(ValueError, match="discovered no stable failure"):
        discover_sqlite_two_connection_failure_to_repro(
            (_case(),),
            harness=_harness(same_journal=True),
            destination=destination,
            mutations_per_case=2,
            max_evaluations=3,
            max_corpus_entries=8,
            max_evaluations_per_phase=16,
        )

    assert not destination.exists()
