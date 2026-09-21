import sys

import pytest

from systems_conformance import (
    CandidateBudgetExhausted,
    CommandTarget,
    DifferentialHarness,
    FuzzFailure,
    reduce_failure_to_repro,
)

ECHO_SCRIPT = "import sys; sys.stdout.buffer.write(sys.stdin.buffer.read())"
BUGGY_SCRIPT = (
    "import sys; data = sys.stdin.buffer.read(); "
    "sys.stdout.buffer.write(data.replace(b'BUG', b'BAD'))"
)


def target(script: str) -> CommandTarget:
    return CommandTarget((sys.executable, "-c", script))


def test_real_process_triage_does_not_reinvoke_candidate_factory_after_budget(tmp_path) -> None:
    harness = DifferentialHarness(candidate=target(BUGGY_SCRIPT), oracle=target(ECHO_SCRIPT))
    initial = b"XBUG"
    observed = harness.evaluate(initial)
    assert observed.comparison.classification == "product_mismatch"
    assert observed.signature is not None
    failure = FuzzFailure(
        evaluation_index=0,
        case=initial,
        comparison=observed.comparison,
        signature=observed.signature,
    )
    factory_calls = 0

    def candidates(value: bytes) -> list[bytes]:
        nonlocal factory_calls
        factory_calls += 1
        assert value == initial
        return [b"BUG"]

    destination = tmp_path / "repro"
    with pytest.raises(CandidateBudgetExhausted) as caught:
        reduce_failure_to_repro(
            failure,
            harness=harness,
            destination=destination,
            candidates=candidates,
            max_candidate_visits=1,
        )

    assert caught.value.candidate_visits == 1
    assert caught.value.max_candidate_visits == 1
    assert factory_calls == 1
    assert not destination.exists()
