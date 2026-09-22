from __future__ import annotations

import json

import pytest

from systems_conformance import (
    DifferentialHarness,
    SQLiteTwoConnectionScenarioMutations,
    SQLiteTwoConnectionScenarioTarget,
    run_fuzz_campaign,
)


def _case(*, mode: str = "immediate", threshold: int = 0) -> bytes:
    return json.dumps(
        {
            "setup": [
                "CREATE TABLE items(v INTEGER NOT NULL)",
                "INSERT INTO items VALUES (0)",
            ],
            "steps": [
                {"connection": "a", "op": "begin", "mode": mode},
                {"connection": "a", "op": "execute", "sql": "UPDATE items SET v = 1"},
                {
                    "connection": "b",
                    "op": "try_query",
                    "sql": "SELECT v FROM items WHERE v >= ?",
                    "params": [threshold],
                },
                {"connection": "a", "op": "rollback"},
            ],
        },
        separators=(",", ":"),
    ).encode()


def test_scenario_mutations_are_finite_deterministic_and_preserve_protocol_shape() -> None:
    seed = _case(mode="immediate", threshold=7)
    corpus = SQLiteTwoConnectionScenarioMutations([seed])

    assert corpus(0) == seed
    assert corpus.case_count == 9
    assert json.loads(corpus(1))["steps"][0]["mode"] == "deferred"
    assert json.loads(corpus(2))["steps"][0]["mode"] == "exclusive"
    assert [
        json.loads(corpus(index))["steps"][2]["params"][0]
        for index in range(3, corpus.case_count)
    ] == [0, 1, -1, None, 7.0, "7"]

    assert tuple(corpus[index] for index in range(corpus.case_count)) == tuple(
        SQLiteTwoConnectionScenarioMutations([seed])[index]
        for index in range(corpus.case_count)
    )
    for index in range(1, corpus.case_count):
        decoded = json.loads(corpus(index))
        assert decoded["setup"] == json.loads(seed)["setup"]
        assert len(decoded["steps"]) == 4


def test_scenario_mutations_validate_shape_and_bounds() -> None:
    seed = _case()

    with pytest.raises(ValueError, match="max_case_bytes"):
        SQLiteTwoConnectionScenarioMutations([seed], max_case_bytes=len(seed) - 1)
    with pytest.raises(ValueError, match="exactly setup and steps"):
        SQLiteTwoConnectionScenarioMutations([b'{"steps":[{"connection":"a","op":"rollback"}]}'])
    with pytest.raises(ValueError, match="non-empty"):
        SQLiteTwoConnectionScenarioMutations([b'{"setup":[],"steps":[]}'])
    with pytest.raises(ValueError, match="connection"):
        SQLiteTwoConnectionScenarioMutations(
            [b'{"setup":[],"steps":[{"connection":["c"],"op":"rollback"}]}']
        )
    with pytest.raises(ValueError, match="op is unsupported"):
        SQLiteTwoConnectionScenarioMutations(
            [b'{"setup":[],"steps":[{"connection":"a","op":{"name":"rollback"}}]}']
        )
    with pytest.raises(ValueError, match="mode"):
        SQLiteTwoConnectionScenarioMutations(
            [
                b'{"setup":[],"steps":['
                b'{"connection":"a","op":"begin","mode":"optimistic"}]}'
            ]
        )
    with pytest.raises(TypeError, match="JSON scalar"):
        SQLiteTwoConnectionScenarioMutations(
            [
                b'{"setup":[],"steps":['
                b'{"connection":"a","op":"query","sql":"SELECT ?","params":[[1]]}]}'
            ]
        )


def test_real_sqlite_fuzz_discovers_reader_contention_via_begin_mode() -> None:
    corpus = SQLiteTwoConnectionScenarioMutations([_case(mode="immediate")])
    harness = DifferentialHarness(
        candidate=SQLiteTwoConnectionScenarioTarget(journal_mode="delete").as_command_target(),
        oracle=SQLiteTwoConnectionScenarioTarget(journal_mode="wal").as_command_target(),
        timeout_seconds=5.0,
    )

    assert harness.evaluate(corpus(0)).comparison.classification == "match"
    assert json.loads(corpus(1))["steps"][0]["mode"] == "deferred"
    assert harness.evaluate(corpus(1)).comparison.classification == "match"
    assert json.loads(corpus(2))["steps"][0]["mode"] == "exclusive"

    campaign = run_fuzz_campaign(
        cases=corpus,
        evaluate=harness.compare,
        max_evaluations=corpus.case_count,
    )

    assert campaign.evaluations == 3
    assert campaign.classification == "product_mismatch"
    assert campaign.failing_case == corpus(2)
    assert campaign.comparison is not None
    assert campaign.comparison.candidate_infrastructure_error is None
    assert campaign.comparison.oracle_infrastructure_error is None
    assert campaign.exhausted_budget is False
