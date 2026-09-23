from __future__ import annotations

import gzip
import json
import platform
import shutil
import sys

import pytest

from systems_conformance import (
    CommandTarget,
    DifferentialHarness,
    HTTPContentEncodingNodeTarget,
    HTTPContentEncodingTarget,
    run_failure_discovery_campaign,
)
from systems_conformance.http_content_encoding_adapter import (
    MAX_CONFIGURED_BODY_BYTES,
)

_IDENTITY = 0
_GZIP = 1


def _case(mode: int, body: bytes, *, declared_length: int | None = None) -> bytes:
    length = len(body) if declared_length is None else declared_length
    return bytes([mode]) + length.to_bytes(4, "big") + body


def _harness(
    *,
    max_wire_body_bytes: int = 64 * 1024,
    max_observed_body_bytes: int = 64 * 1024,
) -> DifferentialHarness:
    return DifferentialHarness(
        candidate=HTTPContentEncodingNodeTarget(
            max_wire_body_bytes=max_wire_body_bytes,
            max_observed_body_bytes=max_observed_body_bytes,
        ).as_command_target(),
        oracle=HTTPContentEncodingTarget(
            max_wire_body_bytes=max_wire_body_bytes,
            max_observed_body_bytes=max_observed_body_bytes,
        ).as_command_target(),
        timeout_seconds=8.0,
        max_input_bytes=2 * 1024 * 1024,
        max_output_bytes=256 * 1024,
        max_total_output_bytes=512 * 1024,
    )


def _payload(text: str) -> dict[str, object]:
    return json.loads(text)


@pytest.mark.parametrize("body", [b"", b"hello", bytes.fromhex("000102ff")])
def test_identity_response_body_matches_across_clients(body: bytes) -> None:
    run = _harness().evaluate(_case(_IDENTITY, body))

    assert run.comparison.classification == "match"
    assert run.signature is None
    assert _payload(run.candidate.stdout.text) == {
        "body_hex": body.hex(),
        "content_encoding": None,
        "content_length": str(len(body)),
        "ok": True,
    }


@pytest.mark.parametrize("payload", [b"", b"hello", bytes(range(32))])
def test_gzip_response_surfaces_native_auto_decompression_policy(
    payload: bytes,
) -> None:
    wire = gzip.compress(payload, mtime=0)
    run = _harness().evaluate(_case(_GZIP, wire))

    assert run.comparison.classification == "product_mismatch"
    assert run.comparison.mismatches == ("stdout",)
    assert run.signature is not None
    assert run.signature.kind == "product_mismatch"

    assert _payload(run.candidate.stdout.text) == {
        "body_hex": payload.hex(),
        "content_encoding": "gzip",
        "content_length": str(len(wire)),
        "ok": True,
    }
    assert _payload(run.oracle.stdout.text) == {
        "body_hex": wire.hex(),
        "content_encoding": "gzip",
        "content_length": str(len(wire)),
        "ok": True,
    }


def test_malformed_gzip_surfaces_body_decode_policy_difference() -> None:
    wire = b"not-a-gzip-stream"
    run = _harness().evaluate(_case(_GZIP, wire))

    assert run.comparison.classification == "product_mismatch"
    assert run.comparison.mismatches == ("stdout",)
    assert _payload(run.candidate.stdout.text) == {
        "error": "body_decode_error",
        "ok": False,
    }
    assert _payload(run.oracle.stdout.text) == {
        "body_hex": wire.hex(),
        "content_encoding": "gzip",
        "content_length": str(len(wire)),
        "ok": True,
    }


@pytest.mark.parametrize(
    "case",
    [
        b"",
        b"\x00",
        b"\x02\x00\x00\x00\x00",
        _case(_IDENTITY, b"abc", declared_length=2),
        _case(_GZIP, b"abc", declared_length=4),
    ],
)
def test_invalid_case_protocol_is_rejected_before_loopback_fetch(case: bytes) -> None:
    run = _harness().evaluate(case)

    assert run.comparison.classification == "match"
    assert run.signature is None
    assert _payload(run.candidate.stdout.text) == {
        "error": "protocol_error",
        "ok": False,
    }


def test_declared_wire_body_over_budget_fails_closed_before_fetch() -> None:
    run = _harness(max_wire_body_bytes=4).evaluate(
        _case(_IDENTITY, b"", declared_length=5)
    )

    assert run.comparison.classification == "match"
    assert run.signature is None
    assert _payload(run.candidate.stdout.text) == {
        "error": "wire_body_too_large",
        "ok": False,
    }


def test_case_over_wire_budget_fails_closed_before_protocol_parse() -> None:
    run = _harness(max_wire_body_bytes=4).evaluate(_case(_IDENTITY, b"12345"))

    assert run.comparison.classification == "match"
    assert run.signature is None
    assert _payload(run.candidate.stdout.text) == {
        "error": "case_too_large",
        "ok": False,
    }


def test_exact_observed_body_budget_succeeds_for_identity_response() -> None:
    body = b"12345"
    run = _harness(max_observed_body_bytes=len(body)).evaluate(
        _case(_IDENTITY, body)
    )

    assert run.comparison.classification == "match"
    assert run.signature is None
    assert _payload(run.candidate.stdout.text) == {
        "body_hex": body.hex(),
        "content_encoding": None,
        "content_length": str(len(body)),
        "ok": True,
    }


def test_over_observed_body_budget_fails_closed_for_identity_response() -> None:
    body = b"12345"
    run = _harness(max_observed_body_bytes=len(body) - 1).evaluate(
        _case(_IDENTITY, body)
    )

    assert run.comparison.classification == "match"
    assert run.signature is None
    assert _payload(run.candidate.stdout.text) == {
        "error": "observed_body_too_large",
        "ok": False,
    }


def test_auto_decompression_expansion_is_bounded_after_client_decoding() -> None:
    payload = b"A" * 4096
    wire = gzip.compress(payload, mtime=0)
    assert len(wire) < 128

    run = _harness(max_observed_body_bytes=128).evaluate(_case(_GZIP, wire))

    assert run.comparison.classification == "product_mismatch"
    assert run.comparison.mismatches == ("stdout",)
    assert _payload(run.candidate.stdout.text) == {
        "error": "observed_body_too_large",
        "ok": False,
    }
    assert _payload(run.oracle.stdout.text) == {
        "body_hex": wire.hex(),
        "content_encoding": "gzip",
        "content_length": str(len(wire)),
        "ok": True,
    }


def test_discovery_publishes_and_replays_gzip_auto_decode_difference(
    tmp_path,
) -> None:
    harness = _harness()
    payload = b"replay-me"
    wire = gzip.compress(payload, mtime=0)
    corpus = (
        _case(_IDENTITY, b"plain"),
        _case(_GZIP, wire),
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
        tmp_path / "http-content-encoding-repro",
        input_bytes=failure.case,
        expected_signature=failure.signature,
        metadata={"domain": "http-content-encoding"},
    )
    replay = harness.replay_repro(repro.path)

    assert replay.reproduced is True
    assert replay.run.signature == failure.signature
    assert replay.bundle.metadata["domain"] == "http-content-encoding"


@pytest.mark.parametrize(
    "field",
    ["max_wire_body_bytes", "max_observed_body_bytes"],
)
@pytest.mark.parametrize(
    "value",
    [
        True,
        False,
        0,
        -1,
        MAX_CONFIGURED_BODY_BYTES + 1,
        1.5,
        "8",
        None,
    ],
)
def test_targets_reject_invalid_body_budgets(field: str, value: object) -> None:
    kwargs = {field: value}

    with pytest.raises(ValueError, match=field):
        HTTPContentEncodingTarget(**kwargs)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match=field):
        HTTPContentEncodingNodeTarget(**kwargs)  # type: ignore[arg-type]


def _execute_command(target: CommandTarget, case: bytes) -> object:
    return target.execute(
        case,
        timeout_seconds=5.0,
        max_output_bytes=4096,
        max_total_output_bytes=8192,
    )


def test_python_runtime_identity_is_verified_before_case_input() -> None:
    target = HTTPContentEncodingTarget()
    implementation, python_version = target.runtime_identity
    command = target.as_command_target()

    assert implementation == sys.implementation.name
    assert python_version == platform.python_version()

    argv = list(command.argv)
    argv[argv.index("--python-version") + 1] = "__drift__"
    result = _execute_command(
        CommandTarget(tuple(argv)),
        _case(_IDENTITY, b"hello"),
    )

    assert result.exit_code == 3
    assert result.stdout.text == ""
    assert (
        result.stderr.text.strip()
        == "http_content_encoding_runtime_identity_mismatch"
    )


def test_node_runtime_identity_is_verified_before_case_input() -> None:
    target = HTTPContentEncodingNodeTarget()
    node_version, undici_version, zlib_version = target.runtime_identity
    command = target.as_command_target()

    assert node_version.startswith("v")
    expected_zlib = (
        f"const EXPECTED_ZLIB_VERSION = {json.dumps(zlib_version)};"
    )
    assert (
        f"const EXPECTED_NODE_VERSION = {json.dumps(node_version)};"
        in command.argv[2]
    )
    assert (
        f"const EXPECTED_UNDICI_VERSION = {json.dumps(undici_version)};"
        in command.argv[2]
    )
    assert expected_zlib in command.argv[2]

    drifted_script = command.argv[2].replace(
        expected_zlib,
        'const EXPECTED_ZLIB_VERSION = "__drift__";',
        1,
    )
    result = _execute_command(
        CommandTarget((target.node_executable, "-e", drifted_script)),
        _case(_IDENTITY, b"hello"),
    )

    assert result.exit_code == 3
    assert result.stdout.text == ""
    assert (
        result.stderr.text.strip()
        == "http_content_encoding_runtime_identity_mismatch"
    )


def test_budget_and_runtime_identity_change_replay_context() -> None:
    baseline = HTTPContentEncodingTarget(
        max_wire_body_bytes=64,
        max_observed_body_bytes=64,
    ).as_command_target()
    smaller_wire = HTTPContentEncodingTarget(
        max_wire_body_bytes=32,
        max_observed_body_bytes=64,
    ).as_command_target()
    smaller_observed = HTTPContentEncodingTarget(
        max_wire_body_bytes=64,
        max_observed_body_bytes=32,
    ).as_command_target()

    argv = list(baseline.argv)
    argv[argv.index("--python-version") + 1] = "__different_python__"
    drifted = CommandTarget(tuple(argv))

    baseline_context = DifferentialHarness(
        candidate=baseline,
        oracle=baseline,
    ).replay_context_sha256

    for changed in (smaller_wire, smaller_observed, drifted):
        assert baseline_context != DifferentialHarness(
            candidate=changed,
            oracle=changed,
        ).replay_context_sha256


def test_node_target_requires_available_runtime() -> None:
    assert shutil.which("node") is not None

    with pytest.raises(ValueError, match="node_executable"):
        HTTPContentEncodingNodeTarget(node_executable="")
    with pytest.raises(RuntimeError, match="Node runtime is required"):
        HTTPContentEncodingNodeTarget(
            node_executable="__missing_conformance_node__"
        )
