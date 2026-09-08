import json

import pytest

from systems_conformance import (
    DifferentialHarness,
    SQLiteQueryParameterMutations,
    SQLiteQueryTarget,
    run_fuzz_campaign,
)


def _row_budget_case(*, threshold: int = 1) -> bytes:
    return json.dumps(
        {
            "setup": [
                "CREATE TABLE items(v INTEGER)",
                "INSERT INTO items VALUES(-1)",
                "INSERT INTO items VALUES(0)",
                "INSERT INTO items VALUES(1)",
            ],
            "query": "SELECT v FROM items WHERE v >= ? ORDER BY v",
            "params": [threshold],
        },
        separators=(",", ":"),
    ).encode()


def _fault_case(*, occurrence: int = 99) -> bytes:
    return json.dumps(
        {
            "setup": ["CREATE TABLE items(v INTEGER)", "INSERT INTO items VALUES(1)"],
            "query": "SELECT count(*) AS n FROM items",
            "params": [],
            "fault": {"operation": "setup", "occurrence": occurrence, "kind": "abort"},
        },
        separators=(",", ":"),
    ).encode()


def test_parameter_mutations_are_finite_deterministic_and_cross_type() -> None:
    seed = _row_budget_case(threshold=1)
    corpus = SQLiteQueryParameterMutations([seed])

    assert corpus.case_count == 7
    assert [json.loads(corpus(index))["params"][0] for index in range(1, 7)] == [
        0,
        -1,
        None,
        1.0,
        "1",
        "x",
    ]
    assert corpus(0) == seed
    assert tuple(corpus[index] for index in range(corpus.case_count)) == tuple(
        SQLiteQueryParameterMutations([seed])[index] for index in range(corpus.case_count)
    )


def test_fault_occurrence_mutations_are_bounded_and_preserve_fault_identity() -> None:
    corpus = SQLiteQueryParameterMutations([_fault_case(occurrence=99)])

    assert corpus.case_count == 4
    assert [json.loads(corpus(index))["fault"]["occurrence"] for index in range(1, 4)] == [
        0,
        1,
        2,
    ]
    for index in range(1, 4):
        fault = json.loads(corpus(index))["fault"]
        assert fault["operation"] == "setup"
        assert fault["kind"] == "abort"


def test_parameter_mutations_validate_protocol_and_bounds() -> None:
    seed = _row_budget_case()
    with pytest.raises(ValueError, match="max_case_bytes"):
        SQLiteQueryParameterMutations([seed], max_case_bytes=len(seed) - 1)
    with pytest.raises(TypeError, match="query"):
        SQLiteQueryParameterMutations([b'{"query":1,"params":[]}'])
    with pytest.raises(TypeError, match="params"):
        SQLiteQueryParameterMutations([b'{"query":"SELECT 1","params":{}}'])
    with pytest.raises(ValueError, match="non-finite"):
        SQLiteQueryParameterMutations([b'{"query":"SELECT ?","params":[NaN]}'])
    with pytest.raises(ValueError, match="fault occurrence"):
        SQLiteQueryParameterMutations(
            [b'{"query":"SELECT 1","fault":{"operation":"query","occurrence":-1,"kind":"abort"}}']
        )


def test_real_sqlite_fuzz_discovers_row_budget_difference_via_query_parameter() -> None:
    corpus = SQLiteQueryParameterMutations([_row_budget_case(threshold=1)])
    harness = DifferentialHarness(
        candidate=SQLiteQueryTarget(max_result_rows=1).as_command_target(),
        oracle=SQLiteQueryTarget(max_result_rows=10).as_command_target(),
    )

    assert harness.evaluate(corpus(0)).comparison.classification == "match"
    assert json.loads(corpus(1))["params"] == [0]

    campaign = run_fuzz_campaign(
        cases=corpus,
        evaluate=harness.compare,
        max_evaluations=corpus.case_count,
    )

    assert campaign.evaluations == 2
    assert campaign.classification == "product_mismatch"
    assert campaign.failing_case == corpus(1)
    assert campaign.comparison is not None
    assert campaign.comparison.candidate_infrastructure_error is None
    assert campaign.comparison.oracle_infrastructure_error is None
    assert campaign.exhausted_budget is False


def test_real_sqlite_fuzz_discovers_reachable_setup_fault_occurrence() -> None:
    corpus = SQLiteQueryParameterMutations([_fault_case(occurrence=99)])
    harness = DifferentialHarness(
        candidate=SQLiteQueryTarget(enable_faults=True).as_command_target(),
        oracle=SQLiteQueryTarget(enable_faults=False).as_command_target(),
    )

    assert harness.evaluate(corpus(0)).comparison.classification == "match"
    assert json.loads(corpus(1))["fault"]["occurrence"] == 0

    campaign = run_fuzz_campaign(
        cases=corpus,
        evaluate=harness.compare,
        max_evaluations=corpus.case_count,
    )

    assert campaign.evaluations == 2
    assert campaign.classification == "product_mismatch"
    assert campaign.failing_case == corpus(1)
    assert campaign.comparison is not None
    assert campaign.comparison.candidate_infrastructure_error is None
    assert campaign.comparison.oracle_infrastructure_error is None
    assert campaign.exhausted_budget is False
