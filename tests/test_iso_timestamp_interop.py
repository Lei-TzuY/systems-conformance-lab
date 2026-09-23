from __future__ import annotations

import json
import platform
import shutil
import sys

import pytest

from systems_conformance import (
    CommandTarget,
    DifferentialHarness,
    ISOTimestampNodeTarget,
    ISOTimestampTarget,
    run_failure_discovery_campaign,
)


def _harness() -> DifferentialHarness:
    return DifferentialHarness(
        candidate=ISOTimestampNodeTarget().as_command_target(),
        oracle=ISOTimestampTarget().as_command_target(),
        timeout_seconds=5.0,
        max_input_bytes=4096,
        max_output_bytes=16 * 1024,
        max_total_output_bytes=32 * 1024,
    )


def _payload(text: str) -> dict[str, object]:
    return json.loads(text)


@pytest.mark.parametrize(
    ("raw", "epoch_milliseconds", "iso_utc"),
    [
        (
            b"1970-01-01T00:00:00Z",
            0,
            "1970-01-01T00:00:00.000Z",
        ),
        (
            b"2024-02-29T12:34:56+00:00",
            1_709_210_096_000,
            "2024-02-29T12:34:56.000Z",
        ),
        (
            b"2024-01-02T03:04:05+05:30",
            1_704_144_845_000,
            "2024-01-01T21:34:05.000Z",
        ),
        (
            b"2024-01-02T03:04:05.123456Z",
            1_704_164_645_123,
            "2024-01-02T03:04:05.123Z",
        ),
        (
            b"1969-12-31T23:59:59.9999Z",
            -1,
            "1969-12-31T23:59:59.999Z",
        ),
        (
            b"2024-01-02T03:04:05+0530",
            1_704_144_845_000,
            "2024-01-01T21:34:05.000Z",
        ),
        (
            b"2024-01-02T03:04Z",
            1_704_164_640_000,
            "2024-01-02T03:04:00.000Z",
        ),
    ],
)
def test_explicit_offset_shared_subset_matches_node_and_python(
    raw: bytes,
    epoch_milliseconds: int,
    iso_utc: str,
) -> None:
    run = _harness().evaluate(raw)

    assert run.comparison.classification == "match"
    assert run.signature is None
    assert _payload(run.candidate.stdout.text) == {
        "epoch_milliseconds": epoch_milliseconds,
        "iso_utc": iso_utc,
        "ok": True,
    }


@pytest.mark.parametrize(
    "raw",
    [
        b"2024-13-01T00:00:00Z",
        b"2024-01-01T00:00:60Z",
        b"not-a-timestamp",
    ],
)
def test_shared_invalid_inputs_return_canonical_parse_error(raw: bytes) -> None:
    run = _harness().evaluate(raw)

    assert run.comparison.classification == "match"
    assert run.signature is None
    assert _payload(run.candidate.stdout.text) == {
        "error": "iso_timestamp_parse_error",
        "ok": False,
    }


@pytest.mark.parametrize(
    "raw",
    [
        b"2024-01-02T03:04:05",
        b"2024-01-02",
    ],
)
def test_valid_but_zone_less_inputs_are_rejected_by_contract(raw: bytes) -> None:
    run = _harness().evaluate(raw)

    assert run.comparison.classification == "match"
    assert run.signature is None
    assert _payload(run.candidate.stdout.text) == {
        "error": "timezone_required",
        "ok": False,
    }


@pytest.mark.parametrize("raw", [b"\xff", "2024-01-02T03:04:05Z\N{SNOWMAN}".encode()])
def test_non_ascii_transport_rejects_before_timestamp_parsing(raw: bytes) -> None:
    run = _harness().evaluate(raw)

    assert run.comparison.classification == "match"
    assert run.signature is None
    assert _payload(run.candidate.stdout.text) == {
        "error": "ascii_decode_error",
        "ok": False,
    }


def test_node_accepts_24_hour_rollover_that_python_rejects() -> None:
    run = _harness().evaluate(b"2024-01-02T24:00:00Z")

    assert run.comparison.classification == "product_mismatch"
    assert run.comparison.mismatches == ("stdout",)
    assert run.signature is not None
    assert run.signature.kind == "product_mismatch"
    assert _payload(run.candidate.stdout.text) == {
        "epoch_milliseconds": 1_704_240_000_000,
        "iso_utc": "2024-01-03T00:00:00.000Z",
        "ok": True,
    }
    assert _payload(run.oracle.stdout.text) == {
        "error": "iso_timestamp_parse_error",
        "ok": False,
    }


def test_node_rolls_invalid_day_that_python_rejects() -> None:
    run = _harness().evaluate(b"2024-02-30T00:00:00Z")

    assert run.comparison.classification == "product_mismatch"
    assert run.comparison.mismatches == ("stdout",)
    assert _payload(run.candidate.stdout.text) == {
        "epoch_milliseconds": 1_709_251_200_000,
        "iso_utc": "2024-03-01T00:00:00.000Z",
        "ok": True,
    }
    assert _payload(run.oracle.stdout.text) == {
        "error": "iso_timestamp_parse_error",
        "ok": False,
    }


def test_python_accepts_offset_seconds_that_node_rejects() -> None:
    run = _harness().evaluate(b"2024-01-02T03:04:05+05:30:15")

    assert run.comparison.classification == "product_mismatch"
    assert run.comparison.mismatches == ("stdout",)
    assert _payload(run.candidate.stdout.text) == {
        "error": "iso_timestamp_parse_error",
        "ok": False,
    }
    assert _payload(run.oracle.stdout.text) == {
        "epoch_milliseconds": 1_704_144_830_000,
        "iso_utc": "2024-01-01T21:33:50.000Z",
        "ok": True,
    }


def test_discovery_publishes_and_replays_24_hour_policy_difference(tmp_path) -> None:
    harness = _harness()
    corpus = (
        b"2024-01-02T23:59:59Z",
        b"2024-01-02T24:00:00Z",
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
    assert failure.case == b"2024-01-02T24:00:00Z"
    assert failure.signature.kind == "product_mismatch"
    assert failure.signature.dimensions == ("stdout",)

    repro = harness.write_repro(
        tmp_path / "iso-timestamp-repro",
        input_bytes=failure.case,
        expected_signature=failure.signature,
        metadata={"domain": "iso-timestamp"},
    )
    replay = harness.replay_repro(repro.path)
    assert replay.reproduced is True
    assert replay.run.signature == failure.signature
    assert replay.bundle.metadata["domain"] == "iso-timestamp"


def _execute_command(target: CommandTarget, case: bytes) -> object:
    return target.execute(
        case,
        timeout_seconds=5.0,
        max_output_bytes=4096,
        max_total_output_bytes=8192,
    )


def test_python_runtime_identity_is_bound_and_verified_before_input() -> None:
    target = ISOTimestampTarget()
    implementation, python_version = target.runtime_identity
    command = target.as_command_target()

    assert implementation == sys.implementation.name
    assert python_version == platform.python_version()
    assert command.argv[-4:] == (
        "--python-implementation",
        implementation,
        "--python-version",
        python_version,
    )

    argv = list(command.argv)
    argv[argv.index("--python-version") + 1] = "__drift__"
    result = _execute_command(
        CommandTarget(tuple(argv)),
        b"2024-01-02T03:04:05Z",
    )

    assert result.exit_code == 3
    assert result.stdout.text == ""
    assert result.stderr.text.strip() == "iso_timestamp_runtime_identity_mismatch"


def test_node_runtime_identity_is_bound_and_verified_before_input() -> None:
    target = ISOTimestampNodeTarget()
    node_version, v8_version = target.runtime_identity
    command = target.as_command_target()
    expected_node = f"const EXPECTED_NODE_VERSION = {json.dumps(node_version)};"
    expected_v8 = f"const EXPECTED_V8_VERSION = {json.dumps(v8_version)};"

    assert node_version.startswith("v")
    assert expected_node in command.argv[2]
    assert expected_v8 in command.argv[2]

    drifted_script = command.argv[2].replace(
        expected_v8,
        'const EXPECTED_V8_VERSION = "__drift__";',
        1,
    )
    result = _execute_command(
        CommandTarget((target.node_executable, "-e", drifted_script)),
        b"2024-01-02T03:04:05Z",
    )

    assert result.exit_code == 3
    assert result.stdout.text == ""
    assert result.stderr.text.strip() == "iso_timestamp_runtime_identity_mismatch"


def test_runtime_identity_changes_replay_context() -> None:
    baseline = ISOTimestampTarget().as_command_target()
    argv = list(baseline.argv)
    argv[argv.index("--python-version") + 1] = "__different_python__"
    drifted = CommandTarget(tuple(argv))

    baseline_context = DifferentialHarness(
        candidate=baseline,
        oracle=baseline,
    ).replay_context_sha256
    drifted_context = DifferentialHarness(
        candidate=drifted,
        oracle=drifted,
    ).replay_context_sha256

    assert baseline_context != drifted_context


def test_node_target_requires_available_runtime() -> None:
    assert shutil.which("node") is not None

    with pytest.raises(ValueError, match="node_executable"):
        ISOTimestampNodeTarget(node_executable="")
    with pytest.raises(RuntimeError, match="Node runtime is required"):
        ISOTimestampNodeTarget(node_executable="__missing_conformance_node__")
