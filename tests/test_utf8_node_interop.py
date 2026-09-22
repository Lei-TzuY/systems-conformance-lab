from __future__ import annotations

import json
import shutil

import pytest

from systems_conformance import (
    DeterministicByteMutations,
    DifferentialHarness,
    UTF8DecodeTarget,
    UTF8NodeDecodeTarget,
    run_fuzz_campaign,
)


def _harness(
    *,
    mode: str = "incremental",
    errors: str = "strict",
    chunk_size: int = 1,
) -> DifferentialHarness:
    return DifferentialHarness(
        candidate=UTF8NodeDecodeTarget(
            mode=mode,  # type: ignore[arg-type]
            errors=errors,  # type: ignore[arg-type]
            chunk_size=chunk_size,
        ).as_command_target(),
        oracle=UTF8DecodeTarget(
            mode=mode,  # type: ignore[arg-type]
            errors=errors,  # type: ignore[arg-type]
            chunk_size=chunk_size,
        ).as_command_target(),
        timeout_seconds=5.0,
        max_input_bytes=64 * 1024,
        max_output_bytes=512 * 1024,
        max_total_output_bytes=1024 * 1024,
    )


def _payload(text: str) -> dict[str, object]:
    return json.loads(text)


def test_node_runtime_is_available_for_cross_runtime_suite() -> None:
    executable = shutil.which("node")

    assert executable is not None


@pytest.mark.parametrize("mode", ["oneshot", "incremental"])
@pytest.mark.parametrize("chunk_size", [1, 2, 3, 7])
def test_node_matches_python_for_valid_multibyte_and_bom(
    mode: str,
    chunk_size: int,
) -> None:
    raw = b"\xef\xbb\xbf" + "Aé中🙂Z".encode()

    run = _harness(mode=mode, chunk_size=chunk_size).evaluate(raw)

    assert run.comparison.classification == "match"
    assert run.signature is None
    assert run.candidate.exit_code == 0
    assert run.oracle.exit_code == 0
    assert _payload(run.candidate.stdout.text) == {
        "ok": True,
        "text": "\ufeffAé中🙂Z",
    }


@pytest.mark.parametrize(
    "raw",
    [
        b"\xff",
        b"A\xc3(",
        b"\xe2\x82",
        b"\xf0\x9f\x99",
    ],
)
@pytest.mark.parametrize("mode", ["oneshot", "incremental"])
@pytest.mark.parametrize("chunk_size", [1, 2, 5])
def test_node_strict_rejection_matches_python(
    raw: bytes,
    mode: str,
    chunk_size: int,
) -> None:
    run = _harness(mode=mode, errors="strict", chunk_size=chunk_size).evaluate(raw)

    assert run.comparison.classification == "match"
    assert run.signature is None
    assert _payload(run.candidate.stdout.text) == {
        "error": "unicode_decode_error",
        "ok": False,
    }


@pytest.mark.parametrize(
    "raw",
    [
        b"A\xffB",
        b"A\xe2\x82",
        b"A\xf0(\x8c(B",
    ],
)
@pytest.mark.parametrize("mode", ["oneshot", "incremental"])
@pytest.mark.parametrize("chunk_size", [1, 2, 4])
def test_node_replace_semantics_match_python(
    raw: bytes,
    mode: str,
    chunk_size: int,
) -> None:
    run = _harness(mode=mode, errors="replace", chunk_size=chunk_size).evaluate(raw)

    assert run.comparison.classification == "match"
    assert run.signature is None
    assert run.candidate.stdout.text == run.oracle.stdout.text
    assert _payload(run.candidate.stdout.text)["ok"] is True


def test_cross_runtime_strict_fuzz_schedule_has_no_differential_failure() -> None:
    cases = DeterministicByteMutations(
        (
            b"ASCII",
            "é".encode(),
            "🙂".encode(),
            b"\xef\xbb\xbfZ",
        )
    )
    harness = _harness(mode="incremental", errors="strict", chunk_size=1)

    campaign = run_fuzz_campaign(
        cases=cases,
        evaluate=harness.compare,
        max_evaluations=len(cases),
    )

    assert campaign.classification == "match"
    assert campaign.failing_case is None
    assert campaign.comparison is None
    assert campaign.evaluations == len(cases)
    assert campaign.exhausted_budget is True


@pytest.mark.parametrize("errors", ["ignore", "surrogatepass", "", "STRICT"])
def test_node_target_rejects_unsupported_error_policy(errors: str) -> None:
    with pytest.raises(ValueError, match="errors"):
        UTF8NodeDecodeTarget(errors=errors)  # type: ignore[arg-type]


@pytest.mark.parametrize("mode", ["stream", "", "INCREMENTAL"])
def test_node_target_rejects_unknown_decode_mode(mode: str) -> None:
    with pytest.raises(ValueError, match="mode"):
        UTF8NodeDecodeTarget(mode=mode)  # type: ignore[arg-type]


@pytest.mark.parametrize("chunk_size", [0, -1, True, 1.5])
def test_node_target_rejects_invalid_chunk_size(chunk_size: object) -> None:
    with pytest.raises(ValueError, match="chunk_size"):
        UTF8NodeDecodeTarget(chunk_size=chunk_size)  # type: ignore[arg-type]
