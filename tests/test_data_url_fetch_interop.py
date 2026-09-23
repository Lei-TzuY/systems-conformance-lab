from __future__ import annotations

import json
import platform
import shutil
import sys

import pytest

from systems_conformance import (
    CommandTarget,
    DataURLFetchNodeTarget,
    DataURLFetchTarget,
    DifferentialHarness,
    run_failure_discovery_campaign,
)
from systems_conformance.data_url_fetch_adapter import (
    MAX_CONFIGURED_DATA_URL_BYTES,
)


def _harness(*, max_data_url_bytes: int = 64 * 1024) -> DifferentialHarness:
    return DifferentialHarness(
        candidate=DataURLFetchNodeTarget(
            max_data_url_bytes=max_data_url_bytes
        ).as_command_target(),
        oracle=DataURLFetchTarget(
            max_data_url_bytes=max_data_url_bytes
        ).as_command_target(),
        timeout_seconds=5.0,
        max_input_bytes=128 * 1024,
        max_output_bytes=256 * 1024,
        max_total_output_bytes=512 * 1024,
    )


def _payload(text: str) -> dict[str, object]:
    return json.loads(text)


@pytest.mark.parametrize(
    ("case", "content_type", "body"),
    [
        (
            b"data:,hello",
            "text/plain;charset=US-ASCII",
            b"hello",
        ),
        (
            b"data:text/plain,hello%20world",
            "text/plain",
            b"hello world",
        ),
        (
            b"DATA:text/plain,hi",
            "text/plain",
            b"hi",
        ),
        (
            b"data:application/octet-stream;base64,AAEC/w==",
            "application/octet-stream",
            bytes.fromhex("000102ff"),
        ),
        (
            b"data:text/plain;charset=utf-8,%E2%98%83",
            "text/plain;charset=utf-8",
            "\N{SNOWMAN}".encode(),
        ),
        (
            b"data:text/plain;foo=bar,hi",
            "text/plain;foo=bar",
            b"hi",
        ),
        (
            b"data:text/plain;base64,SGVsbG8%3D",
            "text/plain",
            b"Hello",
        ),
        (
            b"data:text/plain,%FF",
            "text/plain",
            b"\xff",
        ),
        (
            b"data:,",
            "text/plain;charset=US-ASCII",
            b"",
        ),
    ],
)
def test_shared_data_url_fetch_subset_matches(
    case: bytes,
    content_type: str,
    body: bytes,
) -> None:
    run = _harness().evaluate(case)

    assert run.comparison.classification == "match"
    assert run.signature is None
    assert _payload(run.candidate.stdout.text) == {
        "body_hex": body.hex(),
        "content_type": content_type,
        "ok": True,
    }


@pytest.mark.parametrize(
    "case",
    [
        b"data:",
        b"data:text/plain",
        b"data:;base64",
    ],
)
def test_shared_malformed_data_urls_return_canonical_error(case: bytes) -> None:
    run = _harness().evaluate(case)

    assert run.comparison.classification == "match"
    assert run.signature is None
    assert _payload(run.candidate.stdout.text) == {
        "error": "data_url_error",
        "ok": False,
    }


@pytest.mark.parametrize(
    "case",
    [
        b"http://127.0.0.1:9/",
        b"file:///etc/passwd",
        b"javascript:alert(1)",
    ],
)
def test_non_data_schemes_are_rejected_before_native_fetch(case: bytes) -> None:
    run = _harness().evaluate(case)

    assert run.comparison.classification == "match"
    assert run.signature is None
    assert _payload(run.candidate.stdout.text) == {
        "error": "unsupported_scheme",
        "ok": False,
    }


@pytest.mark.parametrize("case", [b"data:,\xff", b"\xffdata:,hello"])
def test_non_ascii_transport_rejects_before_native_fetch(case: bytes) -> None:
    run = _harness().evaluate(case)

    assert run.comparison.classification == "match"
    assert run.signature is None
    assert _payload(run.candidate.stdout.text) == {
        "error": "ascii_decode_error",
        "ok": False,
    }


def test_exact_data_url_byte_budget_succeeds() -> None:
    case = b"data:,abc"
    run = _harness(max_data_url_bytes=len(case)).evaluate(case)

    assert run.comparison.classification == "match"
    assert run.signature is None
    assert _payload(run.candidate.stdout.text) == {
        "body_hex": b"abc".hex(),
        "content_type": "text/plain;charset=US-ASCII",
        "ok": True,
    }


def test_over_data_url_byte_budget_fails_closed_before_native_fetch() -> None:
    case = b"data:,abc"
    run = _harness(max_data_url_bytes=len(case) - 1).evaluate(case)

    assert run.comparison.classification == "match"
    assert run.signature is None
    assert _payload(run.candidate.stdout.text) == {
        "error": "data_url_too_large",
        "ok": False,
    }


def test_missing_base64_padding_surfaces_native_policy_difference() -> None:
    run = _harness().evaluate(b"data:;base64,Zg")

    assert run.comparison.classification == "product_mismatch"
    assert run.comparison.mismatches == ("stdout",)
    assert run.signature is not None
    assert run.signature.kind == "product_mismatch"
    assert _payload(run.candidate.stdout.text) == {
        "body_hex": "66",
        "content_type": "text/plain;charset=US-ASCII",
        "ok": True,
    }
    assert _payload(run.oracle.stdout.text) == {
        "error": "data_url_error",
        "ok": False,
    }


@pytest.mark.parametrize(
    ("case", "python_body"),
    [
        (b"data:;base64,Zg===", b"f"),
        (b"data:;base64,Zm9v$", b"foo"),
        (b"data:;base64,@@@@", b""),
    ],
)
def test_python_forgiving_base64_forms_surface_native_policy_difference(
    case: bytes,
    python_body: bytes,
) -> None:
    run = _harness().evaluate(case)

    assert run.comparison.classification == "product_mismatch"
    assert run.comparison.mismatches == ("stdout",)
    assert _payload(run.candidate.stdout.text) == {
        "error": "data_url_error",
        "ok": False,
    }
    assert _payload(run.oracle.stdout.text) == {
        "body_hex": python_body.hex(),
        "content_type": "text/plain;charset=US-ASCII",
        "ok": True,
    }


def test_case_insensitive_base64_marker_surfaces_cross_layer_policy_difference() -> None:
    run = _harness().evaluate(b"data:;BASE64,Zg==")

    assert run.comparison.classification == "product_mismatch"
    assert run.comparison.mismatches == ("stdout",)
    assert run.signature is not None
    assert run.signature.kind == "product_mismatch"
    assert _payload(run.candidate.stdout.text) == {
        "body_hex": "66",
        "content_type": "text/plain;charset=US-ASCII",
        "ok": True,
    }
    assert _payload(run.oracle.stdout.text) == {
        "body_hex": b"Zg==".hex(),
        "content_type": ";BASE64",
        "ok": True,
    }


def test_discovery_publishes_and_replays_base64_marker_policy_difference(
    tmp_path,
) -> None:
    harness = _harness()
    corpus = (
        b"data:;base64,Zg==",
        b"data:;BASE64,Zg==",
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
        tmp_path / "data-url-repro",
        input_bytes=failure.case,
        expected_signature=failure.signature,
        metadata={"domain": "data-url-fetch"},
    )
    replay = harness.replay_repro(repro.path)

    assert replay.reproduced is True
    assert replay.run.signature == failure.signature
    assert replay.bundle.metadata["domain"] == "data-url-fetch"


@pytest.mark.parametrize(
    "value",
    [
        True,
        False,
        0,
        -1,
        MAX_CONFIGURED_DATA_URL_BYTES + 1,
        1.5,
        "8",
        None,
    ],
)
def test_targets_reject_invalid_data_url_budgets(value: object) -> None:
    with pytest.raises(ValueError, match="max_data_url_bytes"):
        DataURLFetchTarget(max_data_url_bytes=value)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="max_data_url_bytes"):
        DataURLFetchNodeTarget(max_data_url_bytes=value)  # type: ignore[arg-type]


def _execute_command(target: CommandTarget, case: bytes) -> object:
    return target.execute(
        case,
        timeout_seconds=5.0,
        max_output_bytes=4096,
        max_total_output_bytes=8192,
    )


def test_python_runtime_identity_is_bound_and_verified_before_input() -> None:
    target = DataURLFetchTarget()
    implementation, python_version = target.runtime_identity
    command = target.as_command_target()

    assert implementation == sys.implementation.name
    assert python_version == platform.python_version()

    argv = list(command.argv)
    argv[argv.index("--python-version") + 1] = "__drift__"
    result = _execute_command(CommandTarget(tuple(argv)), b"data:,hello")

    assert result.exit_code == 3
    assert result.stdout.text == ""
    assert result.stderr.text.strip() == "data_url_runtime_identity_mismatch"


def test_node_runtime_identity_is_bound_and_verified_before_input() -> None:
    target = DataURLFetchNodeTarget()
    node_version, undici_version = target.runtime_identity
    command = target.as_command_target()
    expected_node = f"const EXPECTED_NODE_VERSION = {json.dumps(node_version)};"
    expected_undici = (
        f"const EXPECTED_UNDICI_VERSION = {json.dumps(undici_version)};"
    )

    assert node_version.startswith("v")
    assert expected_node in command.argv[2]
    assert expected_undici in command.argv[2]

    drifted_script = command.argv[2].replace(
        expected_undici,
        'const EXPECTED_UNDICI_VERSION = "__drift__";',
        1,
    )
    result = _execute_command(
        CommandTarget((target.node_executable, "-e", drifted_script)),
        b"data:,hello",
    )

    assert result.exit_code == 3
    assert result.stdout.text == ""
    assert result.stderr.text.strip() == "data_url_runtime_identity_mismatch"


def test_budget_and_runtime_identity_change_replay_context() -> None:
    baseline = DataURLFetchTarget(max_data_url_bytes=64).as_command_target()
    smaller = DataURLFetchTarget(max_data_url_bytes=32).as_command_target()
    argv = list(baseline.argv)
    argv[argv.index("--python-version") + 1] = "__different_python__"
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
        DataURLFetchNodeTarget(node_executable="")
    with pytest.raises(RuntimeError, match="Node runtime is required"):
        DataURLFetchNodeTarget(node_executable="__missing_conformance_node__")
