from __future__ import annotations

import json
import platform
import shutil
import sys

import pytest

from systems_conformance import (
    CommandTarget,
    DifferentialHarness,
    URLNodeResolutionTarget,
    URLResolutionTarget,
    run_failure_discovery_campaign,
)


def _case(base: bytes, reference: bytes) -> bytes:
    return len(base).to_bytes(4, "big") + base + reference


def _harness() -> DifferentialHarness:
    return DifferentialHarness(
        candidate=URLNodeResolutionTarget().as_command_target(),
        oracle=URLResolutionTarget().as_command_target(),
        timeout_seconds=5.0,
        max_input_bytes=32 * 1024,
        max_output_bytes=64 * 1024,
        max_total_output_bytes=128 * 1024,
    )


def _payload(text: str) -> dict[str, object]:
    return json.loads(text)


@pytest.mark.parametrize(
    ("base", "reference", "expected"),
    [
        (
            b"https://example.com/a/b/c?old=1#old",
            b"../d",
            {
                "fragment": "",
                "hostname": "example.com",
                "ok": True,
                "password": "",
                "path": "/a/d",
                "port": "",
                "query": "",
                "scheme": "https",
                "username": "",
            },
        ),
        (
            b"https://example.com/a/b/c?old=1#old",
            b"./d?x=1#f",
            {
                "fragment": "f",
                "hostname": "example.com",
                "ok": True,
                "password": "",
                "path": "/a/b/d",
                "port": "",
                "query": "x=1",
                "scheme": "https",
                "username": "",
            },
        ),
        (
            b"https://example.com/a/b/c?old=1#old",
            b"?q=2",
            {
                "fragment": "",
                "hostname": "example.com",
                "ok": True,
                "password": "",
                "path": "/a/b/c",
                "port": "",
                "query": "q=2",
                "scheme": "https",
                "username": "",
            },
        ),
        (
            b"https://example.com/a/b/c?old=1#old",
            b"#frag",
            {
                "fragment": "frag",
                "hostname": "example.com",
                "ok": True,
                "password": "",
                "path": "/a/b/c",
                "port": "",
                "query": "old=1",
                "scheme": "https",
                "username": "",
            },
        ),
        (
            b"https://example.com/a/b/",
            b"//cdn.example.org:8443/x",
            {
                "fragment": "",
                "hostname": "cdn.example.org",
                "ok": True,
                "password": "",
                "path": "/x",
                "port": "8443",
                "query": "",
                "scheme": "https",
                "username": "",
            },
        ),
        (
            b"https://example.com/a/b/",
            b"http://other.example:8080/z",
            {
                "fragment": "",
                "hostname": "other.example",
                "ok": True,
                "password": "",
                "path": "/z",
                "port": "8080",
                "query": "",
                "scheme": "http",
                "username": "",
            },
        ),
    ],
)
def test_node_matches_python_for_shared_relative_resolution_subset(
    base: bytes,
    reference: bytes,
    expected: dict[str, object],
) -> None:
    run = _harness().evaluate(_case(base, reference))

    assert run.comparison.classification == "match"
    assert run.signature is None
    assert run.candidate.exit_code == 0
    assert run.oracle.exit_code == 0
    assert _payload(run.candidate.stdout.text) == expected


@pytest.mark.parametrize(
    "raw",
    [
        b"",
        b"\x00\x00\x00",
        b"\x00\x00\x00\x08abc",
    ],
)
def test_invalid_binary_request_framing_rejects_canonically(raw: bytes) -> None:
    run = _harness().evaluate(raw)

    assert run.comparison.classification == "match"
    assert run.signature is None
    assert _payload(run.candidate.stdout.text) == {
        "error": "request_error",
        "ok": False,
    }


@pytest.mark.parametrize(
    ("base", "reference"),
    [
        (b"https://example.com/\xff", b"x"),
        (b"https://example.com/", b"\xff"),
        (b"https://example.com/\xe2\x82", b"x"),
    ],
)
def test_invalid_utf8_in_either_input_rejects_before_resolution(
    base: bytes,
    reference: bytes,
) -> None:
    run = _harness().evaluate(_case(base, reference))

    assert run.comparison.classification == "match"
    assert run.signature is None
    assert _payload(run.candidate.stdout.text) == {
        "error": "unicode_decode_error",
        "ok": False,
    }


@pytest.mark.parametrize(
    "base",
    [
        b"/relative/base",
        b"mailto:user@example.com",
        b"ftp://example.com/base",
        b"https:///missing-host",
    ],
)
def test_out_of_scope_base_url_rejects_canonically(base: bytes) -> None:
    run = _harness().evaluate(_case(base, b"child"))

    assert run.comparison.classification == "match"
    assert run.signature is None
    assert _payload(run.candidate.stdout.text) == {
        "error": "url_parse_error",
        "ok": False,
    }


@pytest.mark.parametrize(
    ("base", "reference"),
    [
        (b"https://example.com/a/b/", b"..\\d"),
        (b"https://example.com/a/b/c?old=1#old", b""),
    ],
)
def test_native_relative_resolution_semantics_surface_product_mismatches(
    base: bytes,
    reference: bytes,
) -> None:
    run = _harness().evaluate(_case(base, reference))

    assert run.comparison.classification == "product_mismatch"
    assert run.comparison.mismatches == ("stdout",)
    assert run.signature is not None
    assert run.signature.kind == "product_mismatch"
    assert run.signature.dimensions == ("stdout",)


def test_discovery_witness_publishes_and_replays_relative_resolution_divergence(
    tmp_path,
) -> None:
    harness = _harness()
    corpus = (
        _case(b"https://example.com/a/b/", b"../d"),
        _case(b"https://example.com/a/b/", b"..\\d"),
    )

    discovery = run_failure_discovery_campaign(
        cases=corpus.__getitem__,
        evaluate=harness.compare,
        max_evaluations=len(corpus),
        max_unique_failures=4,
    )

    assert discovery.evaluations == len(corpus)
    assert discovery.exhausted_budget is True
    assert discovery.reached_failure_limit is False
    assert len(discovery.failures) == 1
    failure = discovery.failures[0]
    assert failure.evaluation_index == 1
    assert failure.case == corpus[1]
    assert failure.signature.kind == "product_mismatch"
    assert failure.signature.dimensions == ("stdout",)

    repro = harness.write_repro(
        tmp_path / "url-resolution-repro",
        input_bytes=failure.case,
        expected_signature=failure.signature,
        metadata={"domain": "http-url-relative-resolution"},
    )
    assert repro.input_path.read_bytes() == failure.case

    replay = harness.replay_repro(repro.path)
    assert replay.reproduced is True
    assert replay.run.signature == failure.signature
    assert replay.bundle.metadata["domain"] == "http-url-relative-resolution"


def _execute_command(target: CommandTarget, case: bytes) -> object:
    return target.execute(
        case,
        timeout_seconds=5.0,
        max_output_bytes=4096,
        max_total_output_bytes=8192,
    )


def test_python_runtime_identity_is_bound_and_verified_before_input() -> None:
    target = URLResolutionTarget()
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

    drifted_argv = list(command.argv)
    drifted_argv[drifted_argv.index("--python-version") + 1] = "__drift__"
    result = _execute_command(
        CommandTarget(tuple(drifted_argv)),
        _case(b"https://example.com/a/", b"b"),
    )

    assert result.exit_code == 3
    assert result.stdout.text == ""
    assert result.stderr.text.strip() == "url_resolution_runtime_identity_mismatch"


def test_node_runtime_identity_is_bound_and_verified_before_input() -> None:
    target = URLNodeResolutionTarget()
    (node_version,) = target.runtime_identity
    command = target.as_command_target()

    assert node_version.startswith("v")
    expected = f"const EXPECTED_NODE_VERSION = {json.dumps(node_version)};"
    assert expected in command.argv[2]

    drifted_script = command.argv[2].replace(
        expected,
        'const EXPECTED_NODE_VERSION = "__drift__";',
        1,
    )
    assert drifted_script != command.argv[2]
    result = _execute_command(
        CommandTarget((target.node_executable, "-e", drifted_script)),
        _case(b"https://example.com/a/", b"b"),
    )

    assert result.exit_code == 3
    assert result.stdout.text == ""
    assert result.stderr.text.strip() == "url_resolution_runtime_identity_mismatch"


def test_runtime_identity_changes_relative_resolution_replay_context() -> None:
    python_command = URLResolutionTarget().as_command_target()
    python_argv = list(python_command.argv)
    python_argv[python_argv.index("--python-version") + 1] = "__different_python__"
    drifted_python = CommandTarget(tuple(python_argv))

    baseline = DifferentialHarness(candidate=python_command, oracle=python_command)
    changed = DifferentialHarness(candidate=drifted_python, oracle=drifted_python)

    assert baseline.replay_context_sha256 != changed.replay_context_sha256


def test_node_target_requires_available_runtime() -> None:
    assert shutil.which("node") is not None

    with pytest.raises(ValueError, match="node_executable"):
        URLNodeResolutionTarget(node_executable="")
    with pytest.raises(RuntimeError, match="Node runtime is required"):
        URLNodeResolutionTarget(node_executable="__missing_conformance_node__")
