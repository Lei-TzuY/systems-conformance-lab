from __future__ import annotations

import gzip

import pytest

from systems_conformance import (
    DifferentialHarness,
    HTTPChunkedContentEncodingNodeTarget,
    HTTPChunkedContentEncodingTarget,
    reduce_failure_to_repro,
    run_failure_discovery_campaign,
)
from systems_conformance.http_chunked_content_encoding_reducer import (
    http_chunked_content_encoding_reduction_candidates,
)


def _chunked(*chunks: bytes) -> bytes:
    framed = bytearray()
    for chunk in chunks:
        if not chunk:
            continue
        framed.extend(f"{len(chunk):X}\r\n".encode("ascii"))
        framed.extend(chunk)
        framed.extend(b"\r\n")
    framed.extend(b"0\r\n\r\n")
    return bytes(framed)


def _case(mode: int, *chunks: bytes) -> bytes:
    return bytes([mode]) + _chunked(*chunks)


def _harness() -> DifferentialHarness:
    return DifferentialHarness(
        candidate=HTTPChunkedContentEncodingNodeTarget().as_command_target(),
        oracle=HTTPChunkedContentEncodingTarget().as_command_target(),
        timeout_seconds=8.0,
        max_input_bytes=2 * 1024 * 1024,
        max_output_bytes=256 * 1024,
        max_total_output_bytes=512 * 1024,
    )


def test_candidates_are_deterministic_unique_and_strictly_smaller() -> None:
    raw = _case(1, b"abcdef", b"ghij", b"kl")

    first = tuple(http_chunked_content_encoding_reduction_candidates(raw))
    second = tuple(http_chunked_content_encoding_reduction_candidates(raw))

    assert first == second
    assert first
    assert len(first) == len(set(first))
    assert all(len(candidate) < len(raw) for candidate in first)
    assert _case(1, b"abcdefghij", b"kl") in first
    assert _case(1, b"ghij", b"kl") in first


@pytest.mark.parametrize(
    "raw",
    [
        b"",
        b"\x02" + _chunked(b"x"),
        b"\x01Z\r\nx\r\n0\r\n\r\n",
        b"\x011;ext=x\r\nx\r\n0\r\n\r\n",
        b"\x011\r\nx\r\n0\r\nX-Test: y\r\n\r\n",
        b"\x011\r\nx\r\n0\r\n\r\ntrailing",
    ],
)
def test_reducer_fails_closed_on_invalid_or_noncanonical_frames(raw: bytes) -> None:
    with pytest.raises(ValueError):
        tuple(http_chunked_content_encoding_reduction_candidates(raw))


def test_real_chunked_gzip_mismatch_reduces_and_replays(tmp_path) -> None:
    harness = _harness()
    wire = gzip.compress(b"pipeline-reducer", mtime=0)
    witness = _case(1, wire[:3], wire[3:9], wire[9:])
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
        destination=tmp_path / "http-chunked-content-encoding-reduced-repro",
        candidates=http_chunked_content_encoding_reduction_candidates,
        metadata={"domain": "http-chunked-content-encoding-structural-reducer"},
    )

    assert len(reduced.reduction.reduced) < len(witness)
    replay = harness.replay_repro(reduced.repro.path)
    assert replay.reproduced is True
    assert replay.run.signature == failure.signature
    assert (
        replay.bundle.metadata["domain"]
        == "http-chunked-content-encoding-structural-reducer"
    )
