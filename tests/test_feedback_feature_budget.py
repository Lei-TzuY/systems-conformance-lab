import sys

import pytest

from systems_conformance import (
    CommandTarget,
    DifferentialHarness,
    FeatureBudgetExhausted,
    run_feedback_guided_campaign,
)

ECHO_SCRIPT = "import sys; sys.stdout.buffer.write(sys.stdin.buffer.read())"


def test_feedback_campaign_bounds_untrusted_feature_iterator_before_next_pull() -> None:
    pulls = 0

    def features():
        nonlocal pulls
        index = 0
        while True:
            pulls += 1
            yield f"feature:{index}"
            index += 1

    harness = DifferentialHarness(
        candidate=CommandTarget((sys.executable, "-c", ECHO_SCRIPT)),
        oracle=CommandTarget((sys.executable, "-c", ECHO_SCRIPT)),
    )

    def evaluate(case: bytes):
        return harness.evaluate(case).comparison, features()

    with pytest.raises(FeatureBudgetExhausted) as caught:
        run_feedback_guided_campaign(
            seeds=(b"real-process-seed",),
            mutate=lambda case, _index: case,
            evaluate=evaluate,
            max_evaluations=1,
            max_feature_visits_per_evaluation=3,
        )

    assert caught.value.feature_visits == 3
    assert caught.value.max_feature_visits == 3
    assert pulls == 3


def test_feedback_feature_budget_rejects_invalid_limit_before_evaluation() -> None:
    evaluated = False

    def evaluate(case: bytes):
        nonlocal evaluated
        evaluated = True
        raise AssertionError(case)

    with pytest.raises(ValueError, match="max_feature_visits_per_evaluation must be positive"):
        run_feedback_guided_campaign(
            seeds=(b"seed",),
            mutate=lambda case, _index: case,
            evaluate=evaluate,
            max_feature_visits_per_evaluation=0,
        )

    assert not evaluated
