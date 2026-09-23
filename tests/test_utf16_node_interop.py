from __future__ import annotations

import json
import shutil

import pytest

from systems_conformance import (
    DeterministicByteMutations,
    DifferentialHarness,
    UTF16DecodeTarget,
    UTF16NodeDecodeTarget,
    run_fuzz_campaign,
)


def _codec(byte_order: str) -> str:
    return "utf-16-le" if byte_order == "le" else "utf-16-be"


def _encode(text: str, byte_order: str) -> bytes:
    return text.encode(_codec(byte_order))


def _bom(byte_order: str) -> bytes:
    return b"\xff\xfe" if byte_order == "le" else b"\xfe\xff"


def _harness(
    *,
    byte_order: str,
    mode: str = "incremental",
    errors: str = "strict",
    chunk_size: int = 1,
) -> DifferentialHarness:
    return DifferentialHarness(
        candidate=UTF16NodeDecodeTarget(
            byte_order=byte_order,  # type: ignore[arg-type]
            mode=mode,  # type: ignore[arg-type]
            errors=errors,  # type: ignore[arg-type]
            chunk_size=chunk_size,
        ).as_command_target(),
        oracle=UTF16DecodeTarget(
            byte_order=byte_order,  # type: ignore[arg-type]
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


def _malformed_cases(byte_order: str) -> tuple[bytes, ...]:
    if byte_order == "le":
        return (
            b"\x00\xd8",
            b"\x00\xdc",
            b"\x00\xd8A\x00",
            b"A",
        )
    return (
        b"\xd8\x00",
        b"\xdc\x00",
        b"\xd8\x00\x00A",
        b"A",
    )


def test_node_runtime_is_available_for_utf16_interop() -> None:
    assert shutil.which("node") is not None


@pytest.mark.parametrize("byte_order", ["le", "be"])
@pytest.mark.parametrize("mode", ["oneshot", "incremental"])
@pytest.mark.parametrize("chunk_size", [1, 2, 3, 5])
def test_node_matches_python_across_code_unit_and_surrogate_boundaries(
    byte_order: str,
    mode: str,
    chunk_size: int,
) -> None:
    raw = _encode("Aé中🙂Z", byte_order)

    run = _harness(
        byte_order=byte_order,
        mode=mode,
        errors="strict",
        chunk_size=chunk_size,
    ).evaluate(raw)

    assert run.comparison.classification == "match"
    assert run.signature is None
    assert run.candidate.exit_code == 0
    assert run.oracle.exit_code == 0
    assert _payload(run.candidate.stdout.text) == {
        "ok": True,
        "text": "Aé中🙂Z",
    }


@pytest.mark.parametrize("byte_order", ["le", "be"])
@pytest.mark.parametrize("chunk_size", [1, 3, 5])
def test_bom_is_preserved_under_explicit_byte_order(
    byte_order: str,
    chunk_size: int,
) -> None:
    raw = _bom(byte_order) + _encode("A🙂", byte_order)

    run = _harness(
        byte_order=byte_order,
        mode="incremental",
        errors="strict",
        chunk_size=chunk_size,
    ).evaluate(raw)

    assert run.comparison.classification == "match"
    assert run.signature is None
    assert _payload(run.candidate.stdout.text) == {
        "ok": True,
        "text": "\ufeffA🙂",
    }


@pytest.mark.parametrize("byte_order", ["le", "be"])
@pytest.mark.parametrize("chunk_size", [1, 2, 3])
def test_strict_malformed_or_truncated_utf16_rejects_equivalently(
    byte_order: str,
    chunk_size: int,
) -> None:
    for raw in _malformed_cases(byte_order):
        run = _harness(
            byte_order=byte_order,
            mode="incremental",
            errors="strict",
            chunk_size=chunk_size,
        ).evaluate(raw)

        assert run.comparison.classification == "match"
        assert run.signature is None
        assert _payload(run.candidate.stdout.text) == {
            "error": "unicode_decode_error",
            "ok": False,
        }


@pytest.mark.parametrize("byte_order", ["le", "be"])
@pytest.mark.parametrize("chunk_size", [1, 3])
def test_replace_semantics_match_for_malformed_utf16(
    byte_order: str,
    chunk_size: int,
) -> None:
    for raw in _malformed_cases(byte_order):
        run = _harness(
            byte_order=byte_order,
            mode="incremental",
            errors="replace",
            chunk_size=chunk_size,
        ).evaluate(raw)

        assert run.comparison.classification == "match"
        assert run.signature is None
        assert run.candidate.stdout.text == run.oracle.stdout.text
        assert _payload(run.candidate.stdout.text)["ok"] is True


@pytest.mark.parametrize("byte_order", ["le", "be"])
def test_cross_runtime_strict_fuzz_schedule_has_no_differential_failure(
    byte_order: str,
) -> None:
    cases = DeterministicByteMutations(
        (
            _encode("Aé", byte_order),
            _encode("🙂Z", byte_order),
            _bom(byte_order) + _encode("中", byte_order),
        )
    )
    harness = _harness(
        byte_order=byte_order,
        mode="incremental",
        errors="strict",
        chunk_size=1,
    )

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


@pytest.mark.parametrize("byte_order", ["native", "", "LE", "utf-16-le"])
def test_targets_reject_unknown_byte_order(byte_order: str) -> None:
    with pytest.raises(ValueError, match="byte_order"):
        UTF16DecodeTarget(byte_order=byte_order)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="byte_order"):
        UTF16NodeDecodeTarget(byte_order=byte_order)  # type: ignore[arg-type]


@pytest.mark.parametrize("mode", ["stream", "", "INCREMENTAL"])
def test_targets_reject_unknown_decode_mode(mode: str) -> None:
    with pytest.raises(ValueError, match="mode"):
        UTF16DecodeTarget(mode=mode)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="mode"):
        UTF16NodeDecodeTarget(mode=mode)  # type: ignore[arg-type]


@pytest.mark.parametrize("errors", ["ignore", "surrogatepass", "", "STRICT"])
def test_targets_reject_unsupported_error_policy(errors: str) -> None:
    with pytest.raises(ValueError, match="errors"):
        UTF16DecodeTarget(errors=errors)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="errors"):
        UTF16NodeDecodeTarget(errors=errors)  # type: ignore[arg-type]


@pytest.mark.parametrize("chunk_size", [0, -1, True, 1.5])
def test_targets_reject_invalid_chunk_size(chunk_size: object) -> None:
    with pytest.raises(ValueError, match="chunk_size"):
        UTF16DecodeTarget(chunk_size=chunk_size)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="chunk_size"):
        UTF16NodeDecodeTarget(chunk_size=chunk_size)  # type: ignore[arg-type]


def test_node_target_rejects_empty_or_missing_runtime() -> None:
    with pytest.raises(ValueError, match="node_executable"):
        UTF16NodeDecodeTarget(node_executable="")
    with pytest.raises(RuntimeError, match="Node runtime is required"):
        UTF16NodeDecodeTarget(node_executable="__missing_conformance_node__")


def test_byte_order_changes_replay_identity() -> None:
    le_python = UTF16DecodeTarget(byte_order="le").as_command_target()
    be_python = UTF16DecodeTarget(byte_order="be").as_command_target()
    le_node = UTF16NodeDecodeTarget(byte_order="le").as_command_target()
    be_node = UTF16NodeDecodeTarget(byte_order="be").as_command_target()

    assert le_python.argv != be_python.argv
    assert le_node.argv != be_node.argv
    assert DifferentialHarness(
        candidate=le_python,
        oracle=le_python,
    ).replay_context_sha256 != DifferentialHarness(
        candidate=be_python,
        oracle=be_python,
    ).replay_context_sha256
