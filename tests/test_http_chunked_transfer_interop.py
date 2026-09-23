from __future__ import annotations

import json
import platform
import shutil
import sys

import pytest

from systems_conformance import (
    CommandTarget,
    DifferentialHarness,
    HTTPChunkedTransferNodeTarget,
    HTTPChunkedTransferTarget,
    run_failure_discovery_campaign,
)
from systems_conformance.http_chunked_transfer_adapter import (
    MAX_CONFIGURED_BODY_BYTES,
)


def _harness(
    *,
    max_transfer_body_bytes: int = 64 * 1024,
    max_observed_body_bytes: int = 64 * 1024,
) -> DifferentialHarness:
    return DifferentialHarness(
        candidate=HTTPChunkedTransferNodeTarget(
            max_transfer_body_bytes=max_transfer_body_bytes,
            max_observed_body_bytes=max_observed_body_bytes,
        ).as_command_target(),
        oracle=HTTPChunkedTransferTarget(
            max_transfer_body_bytes=max_transfer_body_bytes,
            max_observed_body_bytes=max_observed_body_bytes,
        ).as_command_target(),
        timeout_seconds=8.0,
        max_input_bytes=2 * 1024 * 1024,
        max_output_bytes=256 * 1024,
        max_total_output_bytes=512 * 1024,
    )


def _payload(text: str) -> dict[str, object]:
    return json.loads(text)


@pytest.mark.parametrize(
    ("transfer_body", "body"),
    [
        (b"0\r\n\r\n", b""),
        (b"5\r\nhello\r\n0\r\n\r\n", b"hello"),
        (b"2\r\nhe\r\n3\r\nllo\r\n0\r\n\r\n", b"hello"),
        (b"5;foo=bar\r\nhello\r\n0\r\n\r\n", b"hello"),
        (b"5\r\nhello\r\n0\r\nX-Trailer: yes\r\n\r\n", b"hello"),
        (b"1\r\n\x00\r\n2\r\n\xff\x01\r\n0\r\n\r\n", b"\x00\xff\x01"),
        (b"A\r\n0123456789\r\n0\r\n\r\n", b"0123456789"),
    ],
)
def test_valid_chunked_responses_match_across_clients(
    transfer_body: bytes,
    body: bytes,
) -> None:
    run = _harness().evaluate(transfer_body)

    assert run.comparison.classification == "match"
    assert run.signature is None
    assert _payload(run.candidate.stdout.text) == {
        "body_hex": body.hex(),
        "content_length": None,
        "ok": True,
        "transfer_encoding": "chunked",
    }


@pytest.mark.parametrize(
    "transfer_body",
    [
        b"Z\r\nhello\r\n0\r\n\r\n",
        b"5\nhello\n0\n\n",
    ],
)
def test_shared_malformed_chunk_framing_returns_decode_error(
    transfer_body: bytes,
) -> None:
    run = _harness().evaluate(transfer_body)

    assert run.comparison.classification == "match"
    assert run.signature is None
    assert _payload(run.candidate.stdout.text) == {
        "error": "body_decode_error",
        "ok": False,
    }


def test_missing_terminal_crlf_after_zero_chunk_is_shared_tolerance() -> None:
    transfer_body = b"5\r\nhello\r\n0\r\n"
    run = _harness().evaluate(transfer_body)

    assert run.comparison.classification == "match"
    assert run.signature is None
    assert _payload(run.candidate.stdout.text) == {
        "body_hex": b"hello".hex(),
        "content_length": None,
        "ok": True,
        "transfer_encoding": "chunked",
    }


def test_premature_chunk_close_surfaces_native_policy_difference() -> None:
    transfer_body = b"5\r\nhel"
    run = _harness().evaluate(transfer_body)

    assert run.comparison.classification == "product_mismatch"
    assert run.comparison.mismatches == ("stdout",)
    assert run.signature is not None
    assert run.signature.kind == "product_mismatch"
    assert _payload(run.candidate.stdout.text) == {
        "body_hex": b"hel".hex(),
        "content_length": None,
        "ok": True,
        "transfer_encoding": "chunked",
    }
    assert _payload(run.oracle.stdout.text) == {
        "error": "body_decode_error",
        "ok": False,
    }


def test_exact_transfer_body_budget_succeeds() -> None:
    transfer_body = b"5\r\nhello\r\n0\r\n\r\n"
    run = _harness(max_transfer_body_bytes=len(transfer_body)).evaluate(transfer_body)

    assert run.comparison.classification == "match"
    assert run.signature is None
    assert _payload(run.candidate.stdout.text)["body_hex"] == b"hello".hex()


def test_over_transfer_body_budget_fails_closed_before_loopback_fetch() -> None:
    transfer_body = b"5\r\nhello\r\n0\r\n\r\n"
    run = _harness(max_transfer_body_bytes=len(transfer_body) - 1).evaluate(
        transfer_body
    )

    assert run.comparison.classification == "match"
    assert run.signature is None
    assert _payload(run.candidate.stdout.text) == {
        "error": "transfer_body_too_large",
        "ok": False,
    }


def test_exact_observed_body_budget_succeeds() -> None:
    transfer_body = b"5\r\nhello\r\n0\r\n\r\n"
    run = _harness(max_observed_body_bytes=5).evaluate(transfer_body)

    assert run.comparison.classification == "match"
    assert run.signature is None
    assert _payload(run.candidate.stdout.text)["body_hex"] == b"hello".hex()


def test_over_observed_body_budget_fails_closed() -> None:
    transfer_body = b"5\r\nhello\r\n0\r\n\r\n"
    run = _harness(max_observed_body_bytes=4).evaluate(transfer_body)

    assert run.comparison.classification == "match"
    assert run.signature is None
    assert _payload(run.candidate.stdout.text) == {
        "error": "observed_body_too_large",
        "ok": False,
    }


def test_discovery_publishes_and_replays_premature_chunk_difference(
    tmp_path,
) -> None:
    harness = _harness()
    corpus = (
        b"3\r\nabc\r\n0\r\n\r\n",
        b"5\r\nhel",
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
        tmp_path / "http-chunked-transfer-repro",
        input_bytes=failure.case,
        expected_signature=failure.signature,
        metadata={"domain": "http-chunked-transfer"},
    )
    replay = harness.replay_repro(repro.path)

    assert replay.reproduced is True
    assert replay.run.signature == failure.signature
    assert replay.bundle.metadata["domain"] == "http-chunked-transfer"


@pytest.mark.parametrize(
    "field",
    ["max_transfer_body_bytes", "max_observed_body_bytes"],
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
        HTTPChunkedTransferTarget(**kwargs)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match=field):
        HTTPChunkedTransferNodeTarget(**kwargs)  # type: ignore[arg-type]


def _execute_command(target: CommandTarget, case: bytes) -> object:
    return target.execute(
        case,
        timeout_seconds=5.0,
        max_output_bytes=4096,
        max_total_output_bytes=8192,
    )


def test_python_runtime_identity_is_verified_before_case_input() -> None:
    target = HTTPChunkedTransferTarget()
    implementation, python_version = target.runtime_identity
    command = target.as_command_target()

    assert implementation == sys.implementation.name
    assert python_version == platform.python_version()

    argv = list(command.argv)
    argv[argv.index("--python-version") + 1] = "__drift__"
    result = _execute_command(
        CommandTarget(tuple(argv)),
        b"0\r\n\r\n",
    )

    assert result.exit_code == 3
    assert result.stdout.text == ""
    assert (
        result.stderr.text.strip()
        == "http_chunked_transfer_runtime_identity_mismatch"
    )


def test_node_runtime_identity_is_verified_before_case_input() -> None:
    target = HTTPChunkedTransferNodeTarget()
    node_version, undici_version = target.runtime_identity
    command = target.as_command_target()

    assert node_version.startswith("v")
    expected_undici = (
        f"const EXPECTED_UNDICI_VERSION = {json.dumps(undici_version)};"
    )
    assert (
        f"const EXPECTED_NODE_VERSION = {json.dumps(node_version)};"
        in command.argv[2]
    )
    assert expected_undici in command.argv[2]

    drifted_script = command.argv[2].replace(
        expected_undici,
        'const EXPECTED_UNDICI_VERSION = "__drift__";',
        1,
    )
    result = _execute_command(
        CommandTarget((target.node_executable, "-e", drifted_script)),
        b"0\r\n\r\n",
    )

    assert result.exit_code == 3
    assert result.stdout.text == ""
    assert (
        result.stderr.text.strip()
        == "http_chunked_transfer_runtime_identity_mismatch"
    )


def test_budget_and_runtime_identity_change_replay_context() -> None:
    baseline = HTTPChunkedTransferTarget(
        max_transfer_body_bytes=64,
        max_observed_body_bytes=64,
    ).as_command_target()
    smaller_transfer = HTTPChunkedTransferTarget(
        max_transfer_body_bytes=32,
        max_observed_body_bytes=64,
    ).as_command_target()
    smaller_observed = HTTPChunkedTransferTarget(
        max_transfer_body_bytes=64,
        max_observed_body_bytes=32,
    ).as_command_target()

    argv = list(baseline.argv)
    argv[argv.index("--python-version") + 1] = "__different_python__"
    drifted = CommandTarget(tuple(argv))

    baseline_context = DifferentialHarness(
        candidate=baseline,
        oracle=baseline,
    ).replay_context_sha256

    for changed in (smaller_transfer, smaller_observed, drifted):
        assert baseline_context != DifferentialHarness(
            candidate=changed,
            oracle=changed,
        ).replay_context_sha256


def test_node_target_requires_available_runtime() -> None:
    assert shutil.which("node") is not None

    with pytest.raises(ValueError, match="node_executable"):
        HTTPChunkedTransferNodeTarget(node_executable="")
    with pytest.raises(RuntimeError, match="Node runtime is required"):
        HTTPChunkedTransferNodeTarget(
            node_executable="__missing_conformance_node__"
        )
