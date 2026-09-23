from __future__ import annotations

import json
import platform
import shutil
import sys
import unicodedata

import pytest

from systems_conformance import (
    CommandTarget,
    DifferentialHarness,
    IDNAHostnameTarget,
    IDNANodeHostnameTarget,
    run_failure_discovery_campaign,
)


def _harness() -> DifferentialHarness:
    return DifferentialHarness(
        candidate=IDNANodeHostnameTarget().as_command_target(),
        oracle=IDNAHostnameTarget().as_command_target(),
        timeout_seconds=5.0,
        max_input_bytes=16 * 1024,
        max_output_bytes=64 * 1024,
        max_total_output_bytes=128 * 1024,
    )


def _payload(text: str) -> dict[str, object]:
    return json.loads(text)


@pytest.mark.parametrize(
    ("hostname", "expected"),
    [
        ("example.com", "example.com"),
        ("bücher.example", "xn--bcher-kva.example"),
        ("mañana.com", "xn--maana-pta.com"),
        ("例え.テスト", "xn--r8jz45g.xn--zckzah"),
        ("xn--bcher-kva.example", "xn--bcher-kva.example"),
        ("Ａ.com", "a.com"),
        ("☃.net", "xn--n3h.net"),
        ("www。example．com", "www.example.com"),
        ("example.com.", "example.com."),
    ],
)
def test_node_matches_python_for_shared_idna_subset(
    hostname: str,
    expected: str,
) -> None:
    run = _harness().evaluate(hostname.encode("utf-8"))

    assert run.comparison.classification == "match"
    assert run.signature is None
    assert run.candidate.exit_code == 0
    assert run.oracle.exit_code == 0
    assert _payload(run.candidate.stdout.text) == {
        "ascii": expected,
        "ok": True,
    }


@pytest.mark.parametrize(
    "raw",
    [
        b"\xff",
        b"a\xc3(.com",
        b"\xe2\x82",
    ],
)
def test_invalid_utf8_rejects_before_idna_processing(raw: bytes) -> None:
    run = _harness().evaluate(raw)

    assert run.comparison.classification == "match"
    assert run.signature is None
    assert _payload(run.candidate.stdout.text) == {
        "error": "unicode_decode_error",
        "ok": False,
    }


def test_empty_hostname_rejects_canonically() -> None:
    run = _harness().evaluate(b"")

    assert run.comparison.classification == "match"
    assert run.signature is None
    assert _payload(run.candidate.stdout.text) == {
        "error": "idna_error",
        "ok": False,
    }


@pytest.mark.parametrize(
    ("hostname", "node_value", "python_value"),
    [
        (
            "faß.de",
            {"ascii": "xn--fa-hia.de", "ok": True},
            {"ascii": "fass.de", "ok": True},
        ),
        (
            "a\u200db.com",
            {"error": "idna_error", "ok": False},
            {"ascii": "ab.com", "ok": True},
        ),
        (
            "EXAMPLE.COM",
            {"ascii": "example.com", "ok": True},
            {"ascii": "EXAMPLE.COM", "ok": True},
        ),
    ],
)
def test_native_idna_policy_differences_surface_as_product_mismatches(
    hostname: str,
    node_value: dict[str, object],
    python_value: dict[str, object],
) -> None:
    run = _harness().evaluate(hostname.encode("utf-8"))

    assert run.comparison.classification == "product_mismatch"
    assert run.comparison.mismatches == ("stdout",)
    assert run.signature is not None
    assert run.signature.kind == "product_mismatch"
    assert run.signature.dimensions == ("stdout",)
    assert _payload(run.candidate.stdout.text) == node_value
    assert _payload(run.oracle.stdout.text) == python_value


def test_discovery_witness_publishes_and_replays_idna_divergence(tmp_path) -> None:
    harness = _harness()
    corpus = (
        "bücher.example".encode(),
        "faß.de".encode(),
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
        tmp_path / "idna-repro",
        input_bytes=failure.case,
        expected_signature=failure.signature,
        metadata={"domain": "idna-hostname-interop"},
    )
    assert repro.input_path.read_bytes() == failure.case

    replay = harness.replay_repro(repro.path)
    assert replay.reproduced is True
    assert replay.run.signature == failure.signature
    assert replay.bundle.metadata["domain"] == "idna-hostname-interop"


def _execute_command(target: CommandTarget, case: bytes = b"example.com"):
    return target.execute(
        case,
        timeout_seconds=5.0,
        max_output_bytes=4096,
        max_total_output_bytes=8192,
    )


def test_python_runtime_identity_binds_idna_unicode_table() -> None:
    target = IDNAHostnameTarget()
    command = target.as_command_target()
    implementation, python_version, idna_unicode_version = target.runtime_identity

    assert implementation == sys.implementation.name
    assert python_version == platform.python_version()
    assert idna_unicode_version == unicodedata.ucd_3_2_0.unidata_version
    assert command.argv[-6:] == (
        "--python-implementation",
        implementation,
        "--python-version",
        python_version,
        "--idna-unicode-version",
        idna_unicode_version,
    )


def test_python_worker_rejects_idna_runtime_identity_drift_before_input() -> None:
    command = IDNAHostnameTarget().as_command_target()
    argv = list(command.argv)
    argv[argv.index("--idna-unicode-version") + 1] = "__drift__"

    result = _execute_command(CommandTarget(tuple(argv)))

    assert result.exit_code == 3
    assert result.timed_out is False
    assert result.stdout.text == ""
    assert result.stderr.text.strip() == "idna_hostname_runtime_identity_mismatch"


def test_python_runtime_identity_changes_replay_context() -> None:
    command = IDNAHostnameTarget().as_command_target()
    argv = list(command.argv)
    argv[argv.index("--python-version") + 1] = "__different_python__"
    drifted = CommandTarget(tuple(argv))

    baseline = DifferentialHarness(candidate=command, oracle=command)
    changed = DifferentialHarness(candidate=drifted, oracle=drifted)

    assert baseline.replay_context_sha256 != changed.replay_context_sha256


def test_node_runtime_identity_binds_icu_and_unicode_tables() -> None:
    target = IDNANodeHostnameTarget()
    command = target.as_command_target()
    node_version, icu_version, unicode_version = target.runtime_identity
    script = command.argv[2]

    assert node_version.startswith("v")
    assert icu_version
    assert unicode_version
    assert f"const EXPECTED_NODE_VERSION = {json.dumps(node_version)};" in script
    assert f"const EXPECTED_ICU_VERSION = {json.dumps(icu_version)};" in script
    assert f"const EXPECTED_UNICODE_VERSION = {json.dumps(unicode_version)};" in script


def test_node_worker_rejects_runtime_identity_drift_before_input() -> None:
    target = IDNANodeHostnameTarget()
    command = target.as_command_target()
    _node_version, _icu_version, unicode_version = target.runtime_identity
    expected = f"const EXPECTED_UNICODE_VERSION = {json.dumps(unicode_version)};"
    drifted_script = command.argv[2].replace(
        expected,
        'const EXPECTED_UNICODE_VERSION = "__drift__";',
        1,
    )
    assert drifted_script != command.argv[2]

    result = _execute_command(
        CommandTarget((target.node_executable, "-e", drifted_script))
    )

    assert result.exit_code == 3
    assert result.timed_out is False
    assert result.stdout.text == ""
    assert result.stderr.text.strip() == "idna_hostname_runtime_identity_mismatch"


def test_node_runtime_identity_changes_replay_context() -> None:
    target = IDNANodeHostnameTarget()
    command = target.as_command_target()
    node_version, _icu_version, _unicode_version = target.runtime_identity
    expected = f"const EXPECTED_NODE_VERSION = {json.dumps(node_version)};"
    drifted_script = command.argv[2].replace(
        expected,
        'const EXPECTED_NODE_VERSION = "__different_node__";',
        1,
    )
    drifted = CommandTarget((target.node_executable, "-e", drifted_script))

    baseline = DifferentialHarness(candidate=command, oracle=command)
    changed = DifferentialHarness(candidate=drifted, oracle=drifted)

    assert baseline.replay_context_sha256 != changed.replay_context_sha256


def test_node_target_requires_available_runtime() -> None:
    assert shutil.which("node") is not None

    with pytest.raises(ValueError, match="node_executable"):
        IDNANodeHostnameTarget(node_executable="")
    with pytest.raises(RuntimeError, match="Node runtime is required"):
        IDNANodeHostnameTarget(node_executable="__missing_conformance_node__")
