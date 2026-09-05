import pytest

from systems_conformance import ComparisonResult, run_feedback_guided_campaign

MATCH = ComparisonResult(equivalent=True, classification="match", mismatches=())


def test_admits_only_first_witness_for_new_features() -> None:
    def evaluate(case: bytes):
        return MATCH, {case[:1], case[-1:]}

    result = run_feedback_guided_campaign(
        seeds=(b"aa",),
        mutate=lambda case, index: bytes((case[0], ord("b") + index)),
        evaluate=evaluate,
        mutations_per_case=2,
        max_evaluations=5,
    )

    assert [entry.case for entry in result.corpus] == [b"aa", b"ab", b"ac"]
    assert result.features == frozenset({b"a", b"b", b"c"})
    assert result.evaluations == 5
    assert result.exhausted_budget


def test_stops_at_corpus_limit() -> None:
    result = run_feedback_guided_campaign(
        seeds=(0,),
        mutate=lambda case, index: case + index + 1,
        evaluate=lambda case: (MATCH, {case}),
        max_corpus_entries=2,
    )

    assert [entry.case for entry in result.corpus] == [0, 1]
    assert result.reached_corpus_limit
    assert not result.exhausted_budget
    assert result.evaluations == 2


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"seeds": ()}, "seeds"),
        ({"mutations_per_case": 0}, "mutations_per_case"),
        ({"max_evaluations": 0}, "max_evaluations"),
        ({"max_corpus_entries": 0}, "max_corpus_entries"),
    ],
)
def test_rejects_invalid_bounds(kwargs, message) -> None:
    defaults = dict(
        seeds=(b"x",),
        mutate=lambda case, index: case,
        evaluate=lambda case: (MATCH, {case}),
    )
    defaults.update(kwargs)
    with pytest.raises(ValueError, match=message):
        run_feedback_guided_campaign(**defaults)


def test_rejects_inconsistent_comparison() -> None:
    bad = ComparisonResult(equivalent=False, classification="match", mismatches=())
    with pytest.raises(ValueError, match="inconsistent"):
        run_feedback_guided_campaign(
            seeds=(b"x",),
            mutate=lambda case, index: case,
            evaluate=lambda case: (bad, {"feature"}),
        )
