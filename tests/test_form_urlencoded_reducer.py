from __future__ import annotations

import pytest

from systems_conformance import (
    DifferentialHarness,
    FormURLEncodedNodeTarget,
    FormURLEncodedTarget,
    reduce_failure_to_repro,
    run_failure_discovery_campaign,
)
from systems_conformance.form_urlencoded_reducer import (
    form_urlencoded_encode_reduction_candidates,
)


def _encode_case(pairs: list[tuple[str, str]]) -> bytes:
    parts = [len(pairs).to_bytes(4, "big")]
    for key, value in pairs:
        key_bytes = key.encode("utf-8")
        value_bytes = value.encode("utf-8")
        parts.extend(
            (
                len(key_bytes).to_bytes(4, "big"),
                key_bytes,
                len(value_bytes).to_bytes(4, "big"),
                value_bytes,
            )
        )
    return b"".join(parts)


def _harness() -> DifferentialHarness:
    return DifferentialHarness(
        candidate=FormURLEncodedNodeTarget(mode="encode").as_command_target(),
        oracle=FormURLEncodedTarget(mode="encode").as_command_target(),
        timeout_seconds=5.0,
        max_input_bytes=64 * 1024,
        max_output_bytes=512 * 1024,
        max_total_output_bytes=1024 * 1024,
    )


def test_candidates_are_deterministic_unique_smaller_valid_frames() -> None:
    raw = _encode_case([("padding", "ordinary"), ("x", "~ x")])

    first = tuple(form_urlencoded_encode_reduction_candidates(raw))
    second = tuple(form_urlencoded_encode_reduction_candidates(raw))

    assert first == second
    assert len(first) == len(set(first))
    assert first
    assert all(len(candidate) < len(raw) for candidate in first)
    assert _encode_case([("x", "~ x")]) in first
    assert _encode_case([("padding", "ordinary"), ("", "~ x")]) in first


@pytest.mark.parametrize(
    "raw",
    [
        b"",
        b"\x00\x00\x00",
        b"\x00\x00\x00\x01",
        b"\x00\x00\x00\x01\x00\x00\x00\x05abc",
        _encode_case([("a", "1")]) + b"trailing",
        b"\x00\x00\x00\x01\x00\x00\x00\x01\xff\x00\x00\x00\x01x",
    ],
)
def test_reducer_fails_closed_on_invalid_frames(raw: bytes) -> None:
    with pytest.raises(ValueError):
        tuple(form_urlencoded_encode_reduction_candidates(raw))


def test_real_percent_encoding_mismatch_reduces_and_replays(tmp_path) -> None:
    harness = _harness()
    witness = _encode_case([("padding", "ordinary"), ("x", "~ x")])
    discovery = run_failure_discovery_campaign(
        cases=(witness,).__getitem__,
        evaluate=harness.compare,
        max_evaluations=1,
        max_unique_failures=1,
    )

    assert len(discovery.failures) == 1
    failure = discovery.failures[0]
    assert failure.signature.kind == "product_mismatch"
    assert failure.signature.dimensions == ("stdout",)

    reduced = reduce_failure_to_repro(
        failure,
        harness=harness,
        destination=tmp_path / "form-urlencoded-reduced-repro",
        candidates=form_urlencoded_encode_reduction_candidates,
        metadata={"domain": "form-urlencoded-encode-structural-reducer"},
    )

    assert len(reduced.reduction.reduced) < len(witness)
    assert reduced.reduction.reduced == _encode_case([("", "~")])
    replay = harness.replay_repro(reduced.repro.path)
    assert replay.reproduced is True
    assert replay.run.signature == failure.signature
    assert replay.bundle.metadata["domain"] == "form-urlencoded-encode-structural-reducer"
