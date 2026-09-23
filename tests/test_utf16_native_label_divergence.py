from __future__ import annotations

import json
import shutil
from collections.abc import Iterable

import pytest

from systems_conformance import (
    DifferentialHarness,
    UTF16NodeNativeLabelDecodeTarget,
    UTF16PythonNativeDecodeTarget,
    hierarchical_byte_deletions,
    reduce_failure_to_repro,
    run_failure_discovery_campaign,
)


def _le_bom(text: str) -> bytes:
    return b"\xff\xfe" + text.encode("utf-16-le")


def _be_bom(text: str) -> bytes:
    return b"\xfe\xff" + text.encode("utf-16-be")


def _harness(
    *,
    mode: str = "incremental",
    errors: str = "strict",
    chunk_size: int = 1,
) -> DifferentialHarness:
    return DifferentialHarness(
        candidate=UTF16NodeNativeLabelDecodeTarget(
            mode=mode,  # type: ignore[arg-type]
            errors=errors,  # type: ignore[arg-type]
            chunk_size=chunk_size,
        ).as_command_target(),
        oracle=UTF16PythonNativeDecodeTarget(
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


def _be_bom_payload_deletions(value: bytes) -> Iterable[bytes]:
    if not value.startswith(b"\xfe\xff"):
        return
    payload = value[2:]
    for candidate in hierarchical_byte_deletions(payload):
        yield b"\xfe\xff" + candidate


def test_node_runtime_is_available_for_native_utf16_label_suite() -> None:
    assert shutil.which("node") is not None


@pytest.mark.parametrize("mode", ["oneshot", "incremental"])
@pytest.mark.parametrize("chunk_size", [1, 2, 3])
def test_little_endian_bom_is_shared_native_baseline(
    mode: str,
    chunk_size: int,
) -> None:
    run = _harness(mode=mode, errors="strict", chunk_size=chunk_size).evaluate(
        _le_bom("A🙂")
    )

    assert run.comparison.classification == "match"
    assert run.signature is None
    assert _payload(run.candidate.stdout.text) == {
        "ok": True,
        "text": "A🙂",
    }


@pytest.mark.parametrize("mode", ["oneshot", "incremental"])
@pytest.mark.parametrize("errors", ["strict", "replace"])
@pytest.mark.parametrize("chunk_size", [1, 3])
def test_big_endian_bom_exposes_native_label_divergence(
    mode: str,
    errors: str,
    chunk_size: int,
) -> None:
    run = _harness(
        mode=mode,
        errors=errors,
        chunk_size=chunk_size,
    ).evaluate(_be_bom("A"))

    assert run.comparison.classification == "product_mismatch"
    assert run.signature is not None
    assert run.candidate.stdout.text != run.oracle.stdout.text
    assert _payload(run.oracle.stdout.text) == {
        "ok": True,
        "text": "A",
    }


@pytest.mark.parametrize("mode", ["oneshot", "incremental"])
@pytest.mark.parametrize("chunk_size", [1, 2])
def test_missing_bom_exposes_native_contract_divergence(
    mode: str,
    chunk_size: int,
) -> None:
    run = _harness(mode=mode, errors="strict", chunk_size=chunk_size).evaluate(
        "A".encode("utf-16-le")
    )

    assert run.comparison.classification == "product_mismatch"
    assert run.signature is not None
    assert _payload(run.candidate.stdout.text) == {
        "ok": True,
        "text": "A",
    }
    assert _payload(run.oracle.stdout.text) == {
        "error": "unicode_decode_error",
        "ok": False,
    }


def test_discovery_reduction_repro_and_replay_preserve_be_bom_divergence(
    tmp_path,
) -> None:
    harness = _harness(mode="incremental", errors="strict", chunk_size=1)
    cases = (
        _le_bom("A"),
        _be_bom("A🙂Z"),
    )

    discovery = run_failure_discovery_campaign(
        cases=lambda index: cases[index],
        evaluate=harness.compare,
        max_evaluations=len(cases),
        max_unique_failures=4,
    )

    assert discovery.evaluations == len(cases)
    assert discovery.exhausted_budget is True
    assert discovery.reached_failure_limit is False
    assert len(discovery.failures) == 1
    failure = discovery.failures[0]
    assert failure.evaluation_index == 1
    assert failure.case == cases[1]

    reduced = reduce_failure_to_repro(
        failure,
        harness=harness,
        destination=tmp_path / "repro",
        candidates=_be_bom_payload_deletions,
        max_evaluations=64,
        max_candidate_visits=256,
        metadata={"source": "utf16-native-label-divergence"},
    )

    assert reduced.reduction.accepted_steps > 0
    assert reduced.reduction.reduced == b"\xfe\xff"
    assert reduced.repro.input_path.read_bytes() == b"\xfe\xff"

    rerun = harness.evaluate(reduced.reduction.reduced)
    assert rerun.signature == failure.signature
    assert rerun.comparison.classification == "product_mismatch"

    replay = harness.replay_repro(reduced.repro.path)
    assert replay.reproduced is True
    assert replay.run.signature == failure.signature


@pytest.mark.parametrize("mode", ["stream", "", "INCREMENTAL"])
def test_native_targets_reject_unknown_decode_mode(mode: str) -> None:
    with pytest.raises(ValueError, match="mode"):
        UTF16PythonNativeDecodeTarget(mode=mode)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="mode"):
        UTF16NodeNativeLabelDecodeTarget(mode=mode)  # type: ignore[arg-type]


@pytest.mark.parametrize("errors", ["ignore", "surrogatepass", "", "STRICT"])
def test_native_targets_reject_unsupported_error_policy(errors: str) -> None:
    with pytest.raises(ValueError, match="errors"):
        UTF16PythonNativeDecodeTarget(errors=errors)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="errors"):
        UTF16NodeNativeLabelDecodeTarget(errors=errors)  # type: ignore[arg-type]


@pytest.mark.parametrize("chunk_size", [0, -1, True, 1.5])
def test_native_targets_reject_invalid_chunk_size(chunk_size: object) -> None:
    with pytest.raises(ValueError, match="chunk_size"):
        UTF16PythonNativeDecodeTarget(chunk_size=chunk_size)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="chunk_size"):
        UTF16NodeNativeLabelDecodeTarget(chunk_size=chunk_size)  # type: ignore[arg-type]


def test_native_node_target_rejects_missing_runtime() -> None:
    with pytest.raises(ValueError, match="node_executable"):
        UTF16NodeNativeLabelDecodeTarget(node_executable="")
    with pytest.raises(RuntimeError, match="Node runtime is required"):
        UTF16NodeNativeLabelDecodeTarget(
            node_executable="__missing_conformance_node__"
        )


def test_native_streaming_policy_changes_replay_identity() -> None:
    fixed = _harness(mode="incremental", errors="strict", chunk_size=1)
    wider = _harness(mode="incremental", errors="strict", chunk_size=3)

    assert fixed.replay_context_sha256 != wider.replay_context_sha256
