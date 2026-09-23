from __future__ import annotations

import json

import pytest

from systems_conformance import (
    DifferentialHarness,
    JSONParseNodeTarget,
    JSONParseTarget,
    reduce_failure_to_repro,
    run_failure_discovery_campaign,
)
from systems_conformance.json_parser_reducer import (
    MAX_JSON_REDUCER_NESTING_DEPTH,
    json_reduction_candidates,
)


def _harness() -> DifferentialHarness:
    return DifferentialHarness(
        candidate=JSONParseNodeTarget().as_command_target(),
        oracle=JSONParseTarget().as_command_target(),
        timeout_seconds=5.0,
        max_input_bytes=64 * 1024,
        max_output_bytes=256 * 1024,
        max_total_output_bytes=512 * 1024,
    )


def test_candidates_are_deterministic_unique_smaller_valid_json() -> None:
    raw = b'{ "padding": [1, 2, 3], "n": 9007199254740993 }'

    first = tuple(json_reduction_candidates(raw))
    second = tuple(json_reduction_candidates(raw))

    assert first == second
    assert len(first) == len(set(first))
    assert first
    assert all(len(candidate) < len(raw) for candidate in first)
    assert all(json.loads(candidate) is not None for candidate in first)
    assert b'{"n":9007199254740993}' in first


@pytest.mark.parametrize("raw", [b"{", b"NaN", b'"\xff"'])
def test_reducer_fails_closed_on_non_strict_json(raw: bytes) -> None:
    with pytest.raises(ValueError):
        tuple(json_reduction_candidates(raw))


def test_reducer_fails_closed_before_recursive_walk_on_deep_json() -> None:
    depth = MAX_JSON_REDUCER_NESTING_DEPTH + 1
    raw = b"[" * depth + b"0" + b"]" * depth

    assert json.loads(raw) is not None
    with pytest.raises(ValueError, match="reducer nesting depth"):
        tuple(json_reduction_candidates(raw))


def test_real_numeric_precision_mismatch_reduces_and_replays(tmp_path) -> None:
    harness = _harness()
    witness = b'{ "padding": [1, 2, 3], "n": 9007199254740993 }'
    discovery = run_failure_discovery_campaign(
        cases=(witness,).__getitem__,
        evaluate=harness.compare,
        max_evaluations=1,
        max_unique_failures=1,
    )

    assert len(discovery.failures) == 1
    failure = discovery.failures[0]
    assert failure.signature.kind == "product_mismatch"

    reduced = reduce_failure_to_repro(
        failure,
        harness=harness,
        destination=tmp_path / "json-reduced-repro",
        candidates=json_reduction_candidates,
        metadata={"domain": "json-parser-structural-reducer"},
    )

    assert reduced.reduction.reduced == b'{"":9007199254740993}'
    assert len(reduced.reduction.reduced) < len(witness)
    replay = harness.replay_repro(reduced.repro.path)
    assert replay.reproduced is True
    assert replay.run.signature == failure.signature
    assert replay.bundle.metadata["domain"] == "json-parser-structural-reducer"
