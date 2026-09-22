from __future__ import annotations

import json

import pytest

from systems_conformance import (
    DeterministicByteMutations,
    DifferentialHarness,
    UTF8DecodeTarget,
    run_fuzz_campaign,
)


def _harness(
    *,
    errors: str = "strict",
    chunk_size: int = 1,
    chunk_pattern: tuple[int, ...] | None = None,
) -> DifferentialHarness:
    return DifferentialHarness(
        candidate=UTF8DecodeTarget(
            mode="incremental",
            errors=errors,  # type: ignore[arg-type]
            chunk_size=chunk_size,
            chunk_pattern=chunk_pattern,
        ).as_command_target(),
        oracle=UTF8DecodeTarget(
            mode="oneshot",
            errors=errors,  # type: ignore[arg-type]
        ).as_command_target(),
        timeout_seconds=5.0,
        max_input_bytes=64 * 1024,
        max_output_bytes=512 * 1024,
        max_total_output_bytes=1024 * 1024,
    )


def _payload(text: str) -> dict[str, object]:
    return json.loads(text)


@pytest.mark.parametrize("chunk_size", [1, 2, 3, 7])
def test_incremental_matches_oneshot_across_multibyte_chunk_boundaries(
    chunk_size: int,
) -> None:
    raw = "Aé中🙂Z".encode()
    run = _harness(chunk_size=chunk_size).evaluate(raw)

    assert run.comparison.classification == "match"
    assert run.signature is None
    assert run.candidate.exit_code == 0
    assert run.oracle.exit_code == 0
    assert _payload(run.candidate.stdout.text) == {
        "ok": True,
        "text": "Aé中🙂Z",
    }


@pytest.mark.parametrize(
    "chunk_pattern",
    [
        (1, 2, 4),
        (2, 1, 3, 1),
        (4, 1, 2),
    ],
)
def test_incremental_matches_oneshot_with_irregular_chunk_pattern(
    chunk_pattern: tuple[int, ...],
) -> None:
    raw = "Aé中🙂Z".encode()
    run = _harness(chunk_pattern=chunk_pattern).evaluate(raw)

    assert run.comparison.classification == "match"
    assert run.signature is None
    assert _payload(run.candidate.stdout.text) == {
        "ok": True,
        "text": "Aé中🙂Z",
    }


@pytest.mark.parametrize("errors", ["strict", "replace"])
@pytest.mark.parametrize("chunk_pattern", [(1, 3, 2), (2, 1, 1, 4)])
def test_irregular_chunk_pattern_preserves_error_semantics(
    errors: str,
    chunk_pattern: tuple[int, ...],
) -> None:
    raw = b"A\xf0(\x8c(B\xe2\x82"
    run = _harness(
        errors=errors,
        chunk_pattern=chunk_pattern,
    ).evaluate(raw)

    assert run.comparison.classification == "match"
    assert run.signature is None
    assert run.candidate.stdout.text == run.oracle.stdout.text


@pytest.mark.parametrize(
    "raw",
    [
        b"\xff",
        b"A\xc3(",
        b"\xe2\x82",
        b"\xf0\x9f\x99",
    ],
)
@pytest.mark.parametrize("chunk_size", [1, 2, 5])
def test_strict_invalid_or_truncated_utf8_rejects_equivalently(
    raw: bytes,
    chunk_size: int,
) -> None:
    run = _harness(errors="strict", chunk_size=chunk_size).evaluate(raw)

    assert run.comparison.classification == "match"
    assert run.signature is None
    assert _payload(run.candidate.stdout.text) == {
        "error": "unicode_decode_error",
        "ok": False,
    }


@pytest.mark.parametrize("errors", ["replace", "ignore"])
@pytest.mark.parametrize("chunk_size", [1, 2, 4])
def test_non_strict_error_policies_match_across_chunking(
    errors: str,
    chunk_size: int,
) -> None:
    raw = b"A\xf0(\x8c(B\xe2\x82"
    run = _harness(errors=errors, chunk_size=chunk_size).evaluate(raw)

    assert run.comparison.classification == "match"
    assert run.signature is None
    assert _payload(run.candidate.stdout.text)["ok"] is True
    assert run.candidate.stdout.text == run.oracle.stdout.text


def test_deterministic_byte_fuzz_corpus_preserves_streaming_equivalence() -> None:
    cases = DeterministicByteMutations(
        (
            "é".encode(),
            "🙂".encode(),
        )
    )
    harness = _harness(errors="strict", chunk_size=1)

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


@pytest.mark.parametrize("mode", ["stream", "", "INCREMENTAL"])
def test_target_rejects_unknown_decode_mode(mode: str) -> None:
    with pytest.raises(ValueError, match="mode"):
        UTF8DecodeTarget(mode=mode)  # type: ignore[arg-type]


@pytest.mark.parametrize("errors", ["surrogatepass", "", "STRICT"])
def test_target_rejects_unknown_error_policy(errors: str) -> None:
    with pytest.raises(ValueError, match="errors"):
        UTF8DecodeTarget(errors=errors)  # type: ignore[arg-type]


@pytest.mark.parametrize("chunk_size", [0, -1, True, 1.5])
def test_target_rejects_invalid_chunk_size(chunk_size: object) -> None:
    with pytest.raises(ValueError, match="chunk_size"):
        UTF8DecodeTarget(chunk_size=chunk_size)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "chunk_pattern",
    [
        (),
        (1, 0),
        (1, -1),
        (True, 2),
        tuple(1 for _ in range(65)),
    ],
)
def test_target_rejects_invalid_chunk_pattern_value(chunk_pattern: object) -> None:
    with pytest.raises(ValueError, match="chunk_pattern"):
        UTF8DecodeTarget(chunk_pattern=chunk_pattern)  # type: ignore[arg-type]


def test_target_rejects_non_tuple_chunk_pattern() -> None:
    with pytest.raises(TypeError, match="chunk_pattern"):
        UTF8DecodeTarget(chunk_pattern=[1, 2])  # type: ignore[arg-type]


def test_chunk_pattern_changes_target_replay_identity() -> None:
    fixed = UTF8DecodeTarget(mode="incremental", chunk_size=2).as_command_target()
    patterned = UTF8DecodeTarget(
        mode="incremental",
        chunk_size=2,
        chunk_pattern=(1, 3, 2),
    ).as_command_target()

    assert "--chunk-pattern" not in fixed.argv
    assert "--chunk-pattern" in patterned.argv
    assert fixed.argv != patterned.argv
