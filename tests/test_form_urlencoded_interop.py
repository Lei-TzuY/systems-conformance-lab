from __future__ import annotations

import json
import platform
import shutil
import sys

import pytest

from systems_conformance import (
    CommandTarget,
    DifferentialHarness,
    FormURLEncodedNodeTarget,
    FormURLEncodedTarget,
    run_failure_discovery_campaign,
)


def _encode_case(pairs: list[tuple[str, str]]) -> bytes:
    parts = [len(pairs).to_bytes(4, "big")]
    for key, value in pairs:
        key_bytes = key.encode("utf-8")
        value_bytes = value.encode("utf-8")
        parts.extend(
            (
                len(key_bytes).to_bytes(4, "big"),
                key_bytes,
                len(value_bytes).to_bytes(4, "big"),
                value_bytes,
            )
        )
    return b"".join(parts)


def _harness(*, mode: str) -> DifferentialHarness:
    return DifferentialHarness(
        candidate=FormURLEncodedNodeTarget(mode=mode).as_command_target(),  # type: ignore[arg-type]
        oracle=FormURLEncodedTarget(mode=mode).as_command_target(),  # type: ignore[arg-type]
        timeout_seconds=5.0,
        max_input_bytes=64 * 1024,
        max_output_bytes=512 * 1024,
        max_total_output_bytes=1024 * 1024,
    )


def _payload(text: str) -> dict[str, object]:
    return json.loads(text)


@pytest.mark.parametrize(
    ("pairs", "expected"),
    [
        ([("a", "1"), ("b", "two words")], "a=1&b=two+words"),
        ([("x", "é")], "x=%C3%A9"),
        ([("a", "1"), ("a", "2")], "a=1&a=2"),
        ([("x", "a+b c")], "x=a%2Bb+c"),
        ([("", "")], "="),
        ([("例", "値")], "%E4%BE%8B=%E5%80%A4"),
    ],
)
def test_encode_shared_subset_matches_node_and_python(
    pairs: list[tuple[str, str]],
    expected: str,
) -> None:
    run = _harness(mode="encode").evaluate(_encode_case(pairs))

    assert run.comparison.classification == "match"
    assert run.signature is None
    assert run.candidate.exit_code == 0
    assert run.oracle.exit_code == 0
    assert _payload(run.candidate.stdout.text) == {
        "form": expected,
        "ok": True,
    }


@pytest.mark.parametrize(
    ("pairs", "node_form", "python_form"),
    [
        ([("x", "~ x")], "x=%7E+x", "x=~+x"),
        ([("x", "!*()~")], "x=%21*%28%29%7E", "x=%21%2A%28%29~"),
    ],
)
def test_encode_native_percent_encode_policy_differences_surface_product_mismatches(
    pairs: list[tuple[str, str]],
    node_form: str,
    python_form: str,
) -> None:
    run = _harness(mode="encode").evaluate(_encode_case(pairs))

    assert run.comparison.classification == "product_mismatch"
    assert run.comparison.mismatches == ("stdout",)
    assert run.signature is not None
    assert run.signature.kind == "product_mismatch"
    assert run.signature.dimensions == ("stdout",)
    assert _payload(run.candidate.stdout.text) == {"form": node_form, "ok": True}
    assert _payload(run.oracle.stdout.text) == {"form": python_form, "ok": True}


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (b"", []),
        (b"a=1&b=two+words", [["a", "1"], ["b", "two words"]]),
        (b"a=1&a=2", [["a", "1"], ["a", "2"]]),
        (b"x=a%2Bb+c", [["x", "a+b c"]]),
        (b"x=%C3%A9", [["x", "é"]]),
        (b"x=%ZZ", [["x", "%ZZ"]]),
        (b"x", [["x", ""]]),
        (b"x=", [["x", ""]]),
        (b"=value", [["", "value"]]),
    ],
)
def test_decode_shared_subset_matches_node_and_python(
    raw: bytes,
    expected: list[list[str]],
) -> None:
    run = _harness(mode="decode").evaluate(raw)

    assert run.comparison.classification == "match"
    assert run.signature is None
    assert _payload(run.candidate.stdout.text) == {
        "ok": True,
        "pairs": expected,
    }


@pytest.mark.parametrize("raw", [b"x=%FF", b"x=%E2%82"])
def test_decode_invalid_percent_encoded_utf8_surfaces_product_mismatch(raw: bytes) -> None:
    run = _harness(mode="decode").evaluate(raw)

    assert run.comparison.classification == "product_mismatch"
    assert run.comparison.mismatches == ("stdout",)
    assert run.signature is not None
    assert run.signature.kind == "product_mismatch"
    assert run.signature.dimensions == ("stdout",)
    assert _payload(run.candidate.stdout.text) == {
        "ok": True,
        "pairs": [["x", "�"]],
    }
    assert _payload(run.oracle.stdout.text) == {
        "error": "form_decode_error",
        "ok": False,
    }


@pytest.mark.parametrize(
    "raw",
    [
        b"\xff",
        b"x=\xc3(",
        b"\xe2\x82",
    ],
)
def test_decode_invalid_raw_utf8_rejects_before_form_processing(raw: bytes) -> None:
    run = _harness(mode="decode").evaluate(raw)

    assert run.comparison.classification == "match"
    assert run.signature is None
    assert _payload(run.candidate.stdout.text) == {
        "error": "unicode_decode_error",
        "ok": False,
    }


@pytest.mark.parametrize(
    "raw",
    [
        b"",
        b"\x00\x00\x00",
        b"\x00\x00\x00\x01",
        b"\x00\x00\x00\x01\x00\x00\x00\x05abc",
        _encode_case([("a", "1")]) + b"trailing",
    ],
)
def test_encode_invalid_binary_framing_rejects_canonically(raw: bytes) -> None:
    run = _harness(mode="encode").evaluate(raw)

    assert run.comparison.classification == "match"
    assert run.signature is None
    assert _payload(run.candidate.stdout.text) == {
        "error": "request_error",
        "ok": False,
    }


def test_encode_invalid_field_utf8_rejects_before_serialization() -> None:
    raw = (
        (1).to_bytes(4, "big")
        + (1).to_bytes(4, "big")
        + b"\xff"
        + (1).to_bytes(4, "big")
        + b"x"
    )

    run = _harness(mode="encode").evaluate(raw)

    assert run.comparison.classification == "match"
    assert run.signature is None
    assert _payload(run.candidate.stdout.text) == {
        "error": "unicode_decode_error",
        "ok": False,
    }


def test_encode_discovery_publishes_and_replays_percent_encoding_divergence(
    tmp_path,
) -> None:
    harness = _harness(mode="encode")
    corpus = (
        _encode_case([("a", "two words")]),
        _encode_case([("x", "~ x")]),
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
        tmp_path / "form-encode-repro",
        input_bytes=failure.case,
        expected_signature=failure.signature,
        metadata={"domain": "form-urlencoded-encode"},
    )
    replay = harness.replay_repro(repro.path)
    assert replay.reproduced is True
    assert replay.run.signature == failure.signature
    assert replay.bundle.metadata["domain"] == "form-urlencoded-encode"


def test_decode_discovery_publishes_and_replays_invalid_utf8_divergence(
    tmp_path,
) -> None:
    harness = _harness(mode="decode")
    corpus = (
        b"a=two+words",
        b"x=%FF",
    )

    discovery = run_failure_discovery_campaign(
        cases=corpus.__getitem__,
        evaluate=harness.compare,
        max_evaluations=len(corpus),
        max_unique_failures=4,
    )

    assert discovery.evaluations == len(corpus)
    assert discovery.exhausted_budget is True
    assert len(discovery.failures) == 1
    failure = discovery.failures[0]
    assert failure.evaluation_index == 1
    assert failure.signature.kind == "product_mismatch"
    assert failure.signature.dimensions == ("stdout",)

    repro = harness.write_repro(
        tmp_path / "form-decode-repro",
        input_bytes=failure.case,
        expected_signature=failure.signature,
        metadata={"domain": "form-urlencoded-decode"},
    )
    replay = harness.replay_repro(repro.path)
    assert replay.reproduced is True
    assert replay.run.signature == failure.signature
    assert replay.bundle.metadata["domain"] == "form-urlencoded-decode"


@pytest.mark.parametrize("mode", ["ENCODE", "parse", "", "serialize"])
def test_targets_reject_unknown_mode(mode: str) -> None:
    with pytest.raises(ValueError, match="mode"):
        FormURLEncodedTarget(mode=mode)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="mode"):
        FormURLEncodedNodeTarget(mode=mode)  # type: ignore[arg-type]


def _execute_command(target: CommandTarget, case: bytes) -> object:
    return target.execute(
        case,
        timeout_seconds=5.0,
        max_output_bytes=4096,
        max_total_output_bytes=8192,
    )


def test_python_runtime_identity_is_bound_and_verified_before_input() -> None:
    target = FormURLEncodedTarget(mode="decode")
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
    result = _execute_command(CommandTarget(tuple(argv)), b"a=1")

    assert result.exit_code == 3
    assert result.stdout.text == ""
    assert result.stderr.text.strip() == "form_urlencoded_runtime_identity_mismatch"


def test_node_runtime_identity_is_bound_and_verified_before_input() -> None:
    target = FormURLEncodedNodeTarget(mode="decode")
    (node_version,) = target.runtime_identity
    command = target.as_command_target()
    expected = f"const EXPECTED_NODE_VERSION = {json.dumps(node_version)};"

    assert node_version.startswith("v")
    assert expected in command.argv[2]

    drifted_script = command.argv[2].replace(
        expected,
        'const EXPECTED_NODE_VERSION = "__drift__";',
        1,
    )
    result = _execute_command(
        CommandTarget((target.node_executable, "-e", drifted_script)),
        b"a=1",
    )

    assert result.exit_code == 3
    assert result.stdout.text == ""
    assert result.stderr.text.strip() == "form_urlencoded_runtime_identity_mismatch"


def test_mode_and_runtime_identity_change_replay_context() -> None:
    encode = FormURLEncodedTarget(mode="encode").as_command_target()
    decode = FormURLEncodedTarget(mode="decode").as_command_target()
    argv = list(encode.argv)
    argv[argv.index("--python-version") + 1] = "__different_python__"
    drifted = CommandTarget(tuple(argv))

    assert DifferentialHarness(
        candidate=encode,
        oracle=encode,
    ).replay_context_sha256 != DifferentialHarness(
        candidate=decode,
        oracle=decode,
    ).replay_context_sha256
    assert DifferentialHarness(
        candidate=encode,
        oracle=encode,
    ).replay_context_sha256 != DifferentialHarness(
        candidate=drifted,
        oracle=drifted,
    ).replay_context_sha256


def test_node_target_requires_available_runtime() -> None:
    assert shutil.which("node") is not None

    with pytest.raises(ValueError, match="node_executable"):
        FormURLEncodedNodeTarget(node_executable="")
    with pytest.raises(RuntimeError, match="Node runtime is required"):
        FormURLEncodedNodeTarget(node_executable="__missing_conformance_node__")
