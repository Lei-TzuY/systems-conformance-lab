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
                "INSERT INTO parent VALUES(1)",
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


def test_parameter_mutations_are_finite_and_deterministic() -> None:
    seed = _case(parent_id=1)
    corpus = SQLiteTransactionParameterMutations([seed])

    assert corpus.case_count == 3
    assert corpus(0) == seed
    assert json.loads(corpus(1))["transaction"][0]["params"] == [0]
    assert json.loads(corpus(2))["transaction"][0]["params"] == [-1]
    assert tuple(corpus[index] for index in range(corpus.case_count)) == tuple(
        SQLiteTransactionParameterMutations([seed])[index]
        for index in range(corpus.case_count)
    )


def test_parameter_mutations_validate_bounds_and_shape() -> None:
    seed = _case()
    with pytest.raises(ValueError, match="max_case_bytes"):
        SQLiteTransactionParameterMutations([seed], max_case_bytes=len(seed) - 1)
    with pytest.raises(TypeError, match="params"):
        SQLiteTransactionParameterMutations(
            [b'{"transaction":[{"sql":"SELECT 1","params":{}}]}']
        )
    with pytest.raises(ValueError, match="non-empty"):
        SQLiteTransactionParameterMutations([b'{"transaction":[]}'])
    with pytest.raises(ValueError, match="non-finite"):
        SQLiteTransactionParameterMutations(
            [b'{"transaction":[{"sql":"SELECT ?","params":[NaN]}]}']
        )


def test_real_sqlite_fuzz_discovers_foreign_key_difference() -> None:
    corpus = SQLiteTransactionParameterMutations([_case(parent_id=1)])
    harness = DifferentialHarness(
        candidate=SQLiteTransactionTarget(foreign_keys=True).as_command_target(),
        oracle=SQLiteTransactionTarget(foreign_keys=False).as_command_target(),
    )

    initial = harness.evaluate(corpus(0))
    assert initial.comparison.classification == "match"

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
