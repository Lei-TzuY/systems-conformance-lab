import json

import pytest

from systems_conformance import (
    DifferentialHarness,
    SQLiteTransactionParameterMutations,
    SQLiteTransactionTarget,
    run_fuzz_campaign,
)


def _case(*, parent_id: int = 1) -> bytes:
    return json.dumps(
        {
            "setup": [
                "CREATE TABLE parent(id INTEGER PRIMARY KEY)",
                "CREATE TABLE child(parent_id INTEGER REFERENCES parent(id))",
                "INSERT INTO parent VALUES(0)",
                "INSERT INTO parent VALUES(1)",
                "INSERT INTO parent VALUES(-1)",
            ],
            "transaction": [
                {
                    "sql": "INSERT INTO child(parent_id) VALUES (?)",
                    "params": [parent_id],
                }
            ],
            "observe": {"sql": "SELECT count(*) AS n FROM child", "params": []},
        },
        separators=(",", ":"),
    ).encode()


def _observation_case(*, observed_value: int = 0) -> bytes:
    return json.dumps(
        {
            "setup": ["CREATE TABLE items(v INTEGER)"],
            "transaction": [{"sql": "INSERT INTO items VALUES (1)", "params": []}],
            "observe": {
                "sql": "SELECT count(*) AS n FROM items WHERE v = ?",
                "params": [observed_value],
            },
        },
        separators=(",", ":"),
    ).encode()


def test_parameter_mutations_are_finite_deterministic_and_cross_type() -> None:
    seed = _case(parent_id=1)
    corpus = SQLiteTransactionParameterMutations([seed])

    assert corpus.case_count == 7
    expected = [0, -1, None, 1.0, "1", "x"]
    assert [
        json.loads(corpus(index))["transaction"][0]["params"][0]
        for index in range(1, corpus.case_count)
    ] == expected
    assert corpus(0) == seed
    assert tuple(corpus[index] for index in range(corpus.case_count)) == tuple(
        SQLiteTransactionParameterMutations([seed])[index]
        for index in range(corpus.case_count)
    )


def test_cross_type_mutations_preserve_json_scalar_identity() -> None:
    seed = json.dumps(
        {
            "transaction": [{"sql": "SELECT ?", "params": [True]}],
            "observe": {"sql": "SELECT ?", "params": [None]},
        },
        separators=(",", ":"),
    ).encode()
    corpus = SQLiteTransactionParameterMutations([seed])

    transaction_values = [
        json.loads(corpus(index))["transaction"][0]["params"][0]
        for index in range(1, 7)
    ]
    assert transaction_values == [False, None, 0, 1, "0", "1"]
    assert type(transaction_values[2]) is int
    assert type(transaction_values[3]) is int


def test_observation_parameter_mutations_follow_transaction_parameters() -> None:
    seed = json.dumps(
        {
            "transaction": [{"sql": "SELECT ?", "params": [1]}],
            "observe": {"sql": "SELECT ?", "params": [0]},
        },
        separators=(",", ":"),
    ).encode()
    corpus = SQLiteTransactionParameterMutations([seed])

    assert corpus.case_count == 13
    assert json.loads(corpus(1))["transaction"][0]["params"] == [0]
    assert json.loads(corpus(6))["transaction"][0]["params"] == ["x"]
    assert json.loads(corpus(7))["observe"]["params"] == [1]
    assert json.loads(corpus(12))["observe"]["params"] == ["x"]


def test_parameter_mutations_validate_bounds_and_shape() -> None:
    seed = _case()
    with pytest.raises(ValueError, match="max_case_bytes"):
        SQLiteTransactionParameterMutations([seed], max_case_bytes=len(seed) - 1)
    with pytest.raises(TypeError, match="params"):
        SQLiteTransactionParameterMutations(
            [b'{"transaction":[{"sql":"SELECT 1","params":{}}],"observe":{}}']
        )
    with pytest.raises(TypeError, match="observe"):
        SQLiteTransactionParameterMutations(
            [b'{"transaction":[{"sql":"SELECT 1","params":[]}]}']
        )
    with pytest.raises(ValueError, match="non-empty"):
        SQLiteTransactionParameterMutations([b'{"transaction":[],"observe":{}}'])
    with pytest.raises(ValueError, match="non-finite"):
        SQLiteTransactionParameterMutations(
            [b'{"transaction":[{"sql":"SELECT ?","params":[NaN]}],"observe":{}}']
        )
    with pytest.raises(TypeError, match="observe params"):
        SQLiteTransactionParameterMutations(
            [b'{"transaction":[{"sql":"SELECT 1","params":[]}],"observe":{"params":{}}}']
        )


def test_real_sqlite_fuzz_requires_cross_type_value_to_find_fk_difference() -> None:
    corpus = SQLiteTransactionParameterMutations([_case(parent_id=1)])
    harness = DifferentialHarness(
        candidate=SQLiteTransactionTarget(foreign_keys=True).as_command_target(),
        oracle=SQLiteTransactionTarget(foreign_keys=False).as_command_target(),
    )

    for index in range(6):
        assert harness.evaluate(corpus(index)).comparison.classification == "match"
    assert json.loads(corpus(6))["transaction"][0]["params"] == ["x"]

    campaign = run_fuzz_campaign(
        cases=corpus,
        evaluate=harness.compare,
        max_evaluations=corpus.case_count,
    )

    assert campaign.evaluations == 7
    assert campaign.classification == "product_mismatch"
    assert campaign.failing_case == corpus(6)
    assert campaign.comparison is not None
    assert campaign.comparison.candidate_infrastructure_error is None
    assert campaign.comparison.oracle_infrastructure_error is None
    assert campaign.exhausted_budget is False


def test_real_sqlite_fuzz_discovers_commit_difference_via_observation_parameter() -> None:
    corpus = SQLiteTransactionParameterMutations([_observation_case(observed_value=0)])
    harness = DifferentialHarness(
        candidate=SQLiteTransactionTarget(finalize="commit").as_command_target(),
        oracle=SQLiteTransactionTarget(finalize="rollback").as_command_target(),
    )

    initial = harness.evaluate(corpus(0))
    assert initial.comparison.classification == "match"
    assert json.loads(corpus(1))["observe"]["params"] == [1]

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
