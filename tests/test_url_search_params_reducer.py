from __future__ import annotations

import shutil

import pytest

from systems_conformance import (
    DifferentialHarness,
    URLSearchParamsNodeTarget,
    URLSearchParamsOperation,
    URLSearchParamsRequest,
    URLSearchParamsTarget,
    encode_url_search_params_request,
    parse_url_search_params_request,
    reduce_failure_to_repro,
    run_failure_discovery_campaign,
    url_search_params_reduction_candidates,
)

_APPEND = 1
_SORT = 4


def _request() -> URLSearchParamsRequest:
    return URLSearchParamsRequest(
        pairs=(
            (b"noise", b"discard-me"),
            ("😀".encode(), b"supplementary"),
            ("\ue000".encode(), b"bmp-private-use"),
        ),
        operations=(
            URLSearchParamsOperation(_APPEND, (b"unused", b"value")),
            URLSearchParamsOperation(_SORT, ()),
        ),
    )


def _harness() -> DifferentialHarness:
    return DifferentialHarness(
        candidate=URLSearchParamsNodeTarget().as_command_target(),
        oracle=URLSearchParamsTarget().as_command_target(),
        timeout_seconds=5.0,
        max_input_bytes=64 * 1024,
        max_output_bytes=128 * 1024,
        max_total_output_bytes=256 * 1024,
    )


def test_protocol_round_trip_is_exact() -> None:
    request = _request()
    encoded = encode_url_search_params_request(request)

    assert parse_url_search_params_request(encoded) == request
    assert encode_url_search_params_request(parse_url_search_params_request(encoded)) == encoded


@pytest.mark.parametrize(
    "raw",
    [
        b"",
        b"\x00\x00\x00",
        (0).to_bytes(4, "big") + (1).to_bytes(4, "big"),
        (0).to_bytes(4, "big") + (1).to_bytes(4, "big") + b"\xff",
        encode_url_search_params_request(URLSearchParamsRequest((), ())) + b"trailing",
    ],
)
def test_malformed_protocol_is_rejected_fail_closed(raw: bytes) -> None:
    with pytest.raises(ValueError):
        tuple(url_search_params_reduction_candidates(raw))


def test_candidates_are_deterministic_smaller_and_structurally_valid() -> None:
    raw = encode_url_search_params_request(_request())

    first = tuple(url_search_params_reduction_candidates(raw))
    second = tuple(url_search_params_reduction_candidates(raw))

    assert first == second
    assert first
    assert len(first) == len(set(first))
    assert all(len(candidate) < len(raw) for candidate in first)
    assert all(
        encode_url_search_params_request(parse_url_search_params_request(candidate))
        == candidate
        for candidate in first
    )


def test_real_sort_mismatch_reduces_and_replays(tmp_path) -> None:
    assert shutil.which("node") is not None
    harness = _harness()
    raw = encode_url_search_params_request(_request())
    discovery = run_failure_discovery_campaign(
        cases=(raw,).__getitem__,
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
        destination=tmp_path / "url-search-params-reduced",
        candidates=url_search_params_reduction_candidates,
        max_evaluations=128,
        max_candidate_visits=512,
        metadata={"domain": "url-search-params"},
    )

    assert len(reduced.reduction.reduced) < len(raw)
    parsed = parse_url_search_params_request(reduced.reduction.reduced)
    assert URLSearchParamsOperation(_SORT, ()) in parsed.operations
    replay = harness.replay_repro(reduced.repro.path)
    assert replay.reproduced is True
    assert replay.run.signature == failure.signature
    assert replay.bundle.metadata["domain"] == "url-search-params"
