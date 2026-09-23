from __future__ import annotations

import gzip
import json
import platform
import shutil
import sys
import zlib

import pytest

from systems_conformance import (
    CommandTarget,
    DifferentialHarness,
    GzipDecompressionNodeTarget,
    GzipDecompressionTarget,
    run_failure_discovery_campaign,
)
from systems_conformance.gzip_decompression_adapter import (
    MAX_CONFIGURED_DECOMPRESSED_BYTES,
)


def _gzip(raw: bytes) -> bytes:
    return gzip.compress(raw, mtime=0)


def _harness(*, max_decompressed_bytes: int = 64 * 1024) -> DifferentialHarness:
    return DifferentialHarness(
        candidate=GzipDecompressionNodeTarget(
            max_decompressed_bytes=max_decompressed_bytes
        ).as_command_target(),
        oracle=GzipDecompressionTarget(
            max_decompressed_bytes=max_decompressed_bytes
        ).as_command_target(),
        timeout_seconds=5.0,
        max_input_bytes=128 * 1024,
        max_output_bytes=256 * 1024,
        max_total_output_bytes=512 * 1024,
    )


def _payload(text: str) -> dict[str, object]:
    return json.loads(text)


@pytest.mark.parametrize(
    "raw",
    [
        b"",
        b"hello",
        bytes(range(32)),
        b"\x00\xff" * 32,
    ],
)
def test_single_member_shared_subset_matches(raw: bytes) -> None:
    run = _harness().evaluate(_gzip(raw))

    assert run.comparison.classification == "match"
    assert run.signature is None
    assert _payload(run.candidate.stdout.text) == {
        "hex": raw.hex(),
        "ok": True,
    }


def test_concatenated_members_match_and_preserve_member_order() -> None:
    case = _gzip(b"one") + _gzip(b"two") + _gzip(b"three")

    run = _harness().evaluate(case)

    assert run.comparison.classification == "match"
    assert run.signature is None
    assert _payload(run.candidate.stdout.text) == {
        "hex": b"onetwothree".hex(),
        "ok": True,
    }


def test_trailing_zero_padding_is_accepted_by_both_runtimes() -> None:
    case = _gzip(b"hello") + b"\x00\x00\x00"

    run = _harness().evaluate(case)

    assert run.comparison.classification == "match"
    assert run.signature is None
    assert _payload(run.candidate.stdout.text) == {
        "hex": b"hello".hex(),
        "ok": True,
    }


@pytest.mark.parametrize("case_factory", ["not_gzip", "truncated", "crc"])
def test_shared_invalid_gzip_inputs_return_canonical_error(case_factory: str) -> None:
    if case_factory == "not_gzip":
        case = b"not-gzip"
    elif case_factory == "truncated":
        case = _gzip(b"hello")[:-3]
    else:
        encoded = bytearray(_gzip(b"hello"))
        encoded[-8] ^= 0x01
        case = bytes(encoded)

    run = _harness().evaluate(case)

    assert run.comparison.classification == "match"
    assert run.signature is None
    assert _payload(run.candidate.stdout.text) == {
        "error": "gzip_decode_error",
        "ok": False,
    }


def test_exact_decompressed_output_budget_matches() -> None:
    run = _harness(max_decompressed_bytes=8).evaluate(_gzip(b"12345678"))

    assert run.comparison.classification == "match"
    assert run.signature is None
    assert _payload(run.candidate.stdout.text) == {
        "hex": b"12345678".hex(),
        "ok": True,
    }


def test_decompressed_output_over_budget_fails_closed_in_both_runtimes() -> None:
    run = _harness(max_decompressed_bytes=8).evaluate(_gzip(b"123456789"))

    assert run.comparison.classification == "match"
    assert run.signature is None
    assert _payload(run.candidate.stdout.text) == {
        "error": "decompressed_output_too_large",
        "ok": False,
    }


def test_trailing_zero_then_nonzero_byte_surfaces_native_policy_difference() -> None:
    case = _gzip(b"hello") + b"\x00\x01"

    run = _harness().evaluate(case)

    assert run.comparison.classification == "product_mismatch"
    assert run.comparison.mismatches == ("stdout",)
    assert run.signature is not None
    assert run.signature.kind == "product_mismatch"
    assert _payload(run.candidate.stdout.text) == {
        "hex": b"hello".hex(),
        "ok": True,
    }
    assert _payload(run.oracle.stdout.text) == {
        "error": "gzip_decode_error",
        "ok": False,
    }


def test_empty_transport_surfaces_native_policy_difference() -> None:
    run = _harness().evaluate(b"")

    assert run.comparison.classification == "product_mismatch"
    assert run.comparison.mismatches == ("stdout",)
    assert _payload(run.candidate.stdout.text) == {
        "error": "gzip_decode_error",
        "ok": False,
    }
    assert _payload(run.oracle.stdout.text) == {
        "hex": "",
        "ok": True,
    }


def test_discovery_publishes_and_replays_trailing_policy_difference(tmp_path) -> None:
    harness = _harness()
    encoded = _gzip(b"hello")
    corpus = (
        encoded,
        encoded + b"\x00\x01",
    )

    discovery = run_failure_discovery_campaign(
        cases=corpus.__getitem__,
        evaluate=harness.compare,
        max_evaluations=len(corpus),
        max_unique_failures=4,
    )

    assert discovery.evaluations == len(corpus)
    assert len(discovery.failures) == 1
    failure = discovery.failures[0]
    assert failure.evaluation_index == 1
    assert failure.case == corpus[1]
    assert failure.signature.kind == "product_mismatch"
    assert failure.signature.dimensions == ("stdout",)

    repro = harness.write_repro(
        tmp_path / "gzip-repro",
        input_bytes=failure.case,
        expected_signature=failure.signature,
        metadata={"domain": "gzip-decompression"},
    )
    replay = harness.replay_repro(repro.path)
    assert replay.reproduced is True
    assert replay.run.signature == failure.signature
    assert replay.bundle.metadata["domain"] == "gzip-decompression"


@pytest.mark.parametrize(
    "value",
    [
        True,
        False,
        0,
        -1,
        MAX_CONFIGURED_DECOMPRESSED_BYTES + 1,
        1.5,
        "8",
        None,
    ],
)
def test_targets_reject_invalid_decompressed_output_budgets(value: object) -> None:
    with pytest.raises(ValueError, match="max_decompressed_bytes"):
        GzipDecompressionTarget(max_decompressed_bytes=value)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="max_decompressed_bytes"):
        GzipDecompressionNodeTarget(max_decompressed_bytes=value)  # type: ignore[arg-type]


def _execute_command(target: CommandTarget, case: bytes) -> object:
    return target.execute(
        case,
        timeout_seconds=5.0,
        max_output_bytes=4096,
        max_total_output_bytes=8192,
    )


def test_python_runtime_identity_is_bound_and_verified_before_input() -> None:
    target = GzipDecompressionTarget()
    implementation, python_version, zlib_version = target.runtime_identity
    command = target.as_command_target()

    assert implementation == sys.implementation.name
    assert python_version == platform.python_version()
    assert zlib_version == zlib.ZLIB_RUNTIME_VERSION

    argv = list(command.argv)
    argv[argv.index("--zlib-version") + 1] = "__drift__"
    result = _execute_command(CommandTarget(tuple(argv)), _gzip(b"hello"))

    assert result.exit_code == 3
    assert result.stdout.text == ""
    assert result.stderr.text.strip() == "gzip_runtime_identity_mismatch"


def test_node_runtime_identity_is_bound_and_verified_before_input() -> None:
    target = GzipDecompressionNodeTarget()
    node_version, zlib_version = target.runtime_identity
    command = target.as_command_target()
    expected_node = f"const EXPECTED_NODE_VERSION = {json.dumps(node_version)};"
    expected_zlib = f"const EXPECTED_ZLIB_VERSION = {json.dumps(zlib_version)};"

    assert node_version.startswith("v")
    assert expected_node in command.argv[2]
    assert expected_zlib in command.argv[2]

    drifted_script = command.argv[2].replace(
        expected_zlib,
        'const EXPECTED_ZLIB_VERSION = "__drift__";',
        1,
    )
    result = _execute_command(
        CommandTarget((target.node_executable, "-e", drifted_script)),
        _gzip(b"hello"),
    )

    assert result.exit_code == 3
    assert result.stdout.text == ""
    assert result.stderr.text.strip() == "gzip_runtime_identity_mismatch"


def test_budget_and_runtime_identity_change_replay_context() -> None:
    baseline = GzipDecompressionTarget(max_decompressed_bytes=64).as_command_target()
    smaller = GzipDecompressionTarget(max_decompressed_bytes=32).as_command_target()
    argv = list(baseline.argv)
    argv[argv.index("--zlib-version") + 1] = "__different_zlib__"
    drifted = CommandTarget(tuple(argv))

    baseline_context = DifferentialHarness(
        candidate=baseline,
        oracle=baseline,
    ).replay_context_sha256

    for changed in (smaller, drifted):
        assert baseline_context != DifferentialHarness(
            candidate=changed,
            oracle=changed,
        ).replay_context_sha256


def test_node_target_requires_available_runtime() -> None:
    assert shutil.which("node") is not None

    with pytest.raises(ValueError, match="node_executable"):
        GzipDecompressionNodeTarget(node_executable="")
    with pytest.raises(RuntimeError, match="Node runtime is required"):
        GzipDecompressionNodeTarget(node_executable="__missing_conformance_node__")
