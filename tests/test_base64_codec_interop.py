from __future__ import annotations

import json
import platform
import shutil
import sys

import pytest

from systems_conformance import (
    Base64CodecNodeTarget,
    Base64CodecTarget,
    CommandTarget,
    DifferentialHarness,
    run_failure_discovery_campaign,
)


def _harness(*, mode: str, alphabet: str = "base64") -> DifferentialHarness:
    return DifferentialHarness(
        candidate=Base64CodecNodeTarget(
            mode=mode,  # type: ignore[arg-type]
            alphabet=alphabet,  # type: ignore[arg-type]
        ).as_command_target(),
        oracle=Base64CodecTarget(
            mode=mode,  # type: ignore[arg-type]
            alphabet=alphabet,  # type: ignore[arg-type]
        ).as_command_target(),
        timeout_seconds=5.0,
        max_input_bytes=64 * 1024,
        max_output_bytes=256 * 1024,
        max_total_output_bytes=512 * 1024,
    )


def _payload(text: str) -> dict[str, object]:
    return json.loads(text)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (b"", ""),
        (b"f", "Zg=="),
        (b"fo", "Zm8="),
        (b"foo", "Zm9v"),
        (b"hello world", "aGVsbG8gd29ybGQ="),
        (bytes.fromhex("fbff00"), "+/8A"),
    ],
)
def test_standard_encode_shared_subset_matches_node_and_python(
    raw: bytes,
    expected: str,
) -> None:
    run = _harness(mode="encode").evaluate(raw)

    assert run.comparison.classification == "match"
    assert run.signature is None
    assert _payload(run.candidate.stdout.text) == {"encoded": expected, "ok": True}


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (b"", ""),
        (b"foo", "Zm9v"),
        (bytes.fromhex("fbff00"), "-_8A"),
    ],
)
def test_base64url_encode_without_required_padding_matches(
    raw: bytes,
    expected: str,
) -> None:
    run = _harness(mode="encode", alphabet="base64url").evaluate(raw)

    assert run.comparison.classification == "match"
    assert run.signature is None
    assert _payload(run.candidate.stdout.text) == {"encoded": expected, "ok": True}


def test_base64url_padding_policy_surfaces_product_mismatch() -> None:
    run = _harness(mode="encode", alphabet="base64url").evaluate(b"f")

    assert run.comparison.classification == "product_mismatch"
    assert run.comparison.mismatches == ("stdout",)
    assert run.signature is not None
    assert run.signature.kind == "product_mismatch"
    assert _payload(run.candidate.stdout.text) == {"encoded": "Zg", "ok": True}
    assert _payload(run.oracle.stdout.text) == {"encoded": "Zg==", "ok": True}


@pytest.mark.parametrize(
    ("raw", "expected_hex"),
    [
        (b"", ""),
        (b"Zg==", "66"),
        (b"Zm8=", "666f"),
        (b"Zm9v", "666f6f"),
        (b" Zm9v \n", "666f6f"),
        (b"Zm9v$", "666f6f"),
        (b"====", ""),
    ],
)
def test_standard_decode_shared_forgiving_subset_matches(
    raw: bytes,
    expected_hex: str,
) -> None:
    run = _harness(mode="decode").evaluate(raw)

    assert run.comparison.classification == "match"
    assert run.signature is None
    assert _payload(run.candidate.stdout.text) == {"hex": expected_hex, "ok": True}


@pytest.mark.parametrize(
    ("raw", "node_hex"),
    [
        (b"Zg", "66"),
        (b"AA=A", "00"),
        (b"SGVsbG8_", "48656c6c6f3f"),
    ],
)
def test_standard_decode_native_acceptance_differences_surface_product_mismatches(
    raw: bytes,
    node_hex: str,
) -> None:
    run = _harness(mode="decode").evaluate(raw)

    assert run.comparison.classification == "product_mismatch"
    assert run.comparison.mismatches == ("stdout",)
    assert run.signature is not None
    assert run.signature.kind == "product_mismatch"
    assert _payload(run.candidate.stdout.text) == {"hex": node_hex, "ok": True}
    assert _payload(run.oracle.stdout.text) == {
        "error": "base64_decode_error",
        "ok": False,
    }


@pytest.mark.parametrize(
    ("raw", "expected_hex"),
    [
        (b"-_8A", "fbff00"),
        (b"Zm9v", "666f6f"),
    ],
)
def test_base64url_decode_shared_subset_matches(raw: bytes, expected_hex: str) -> None:
    run = _harness(mode="decode", alphabet="base64url").evaluate(raw)

    assert run.comparison.classification == "match"
    assert run.signature is None
    assert _payload(run.candidate.stdout.text) == {"hex": expected_hex, "ok": True}


def test_base64url_missing_padding_surfaces_product_mismatch() -> None:
    run = _harness(mode="decode", alphabet="base64url").evaluate(b"Zg")

    assert run.comparison.classification == "product_mismatch"
    assert run.comparison.mismatches == ("stdout",)
    assert _payload(run.candidate.stdout.text) == {"hex": "66", "ok": True}
    assert _payload(run.oracle.stdout.text) == {
        "error": "base64_decode_error",
        "ok": False,
    }


@pytest.mark.parametrize("raw", [b"\xff", b"Zm9v\x80"])
def test_decode_non_ascii_transport_rejects_before_codec_processing(raw: bytes) -> None:
    run = _harness(mode="decode").evaluate(raw)

    assert run.comparison.classification == "match"
    assert run.signature is None
    assert _payload(run.candidate.stdout.text) == {
        "error": "ascii_decode_error",
        "ok": False,
    }


def test_decode_discovery_publishes_and_replays_missing_padding_divergence(tmp_path) -> None:
    harness = _harness(mode="decode")
    corpus = (b"Zm9v", b"Zg")

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
    assert failure.case == b"Zg"
    assert failure.signature.kind == "product_mismatch"
    assert failure.signature.dimensions == ("stdout",)

    repro = harness.write_repro(
        tmp_path / "base64-decode-repro",
        input_bytes=failure.case,
        expected_signature=failure.signature,
        metadata={"domain": "base64-decode"},
    )
    replay = harness.replay_repro(repro.path)
    assert replay.reproduced is True
    assert replay.run.signature == failure.signature
    assert replay.bundle.metadata["domain"] == "base64-decode"


@pytest.mark.parametrize("mode", ["ENCODE", "parse", "", "serialize"])
def test_targets_reject_unknown_mode(mode: str) -> None:
    with pytest.raises(ValueError, match="mode"):
        Base64CodecTarget(mode=mode)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="mode"):
        Base64CodecNodeTarget(mode=mode)  # type: ignore[arg-type]


@pytest.mark.parametrize("alphabet", ["urlsafe", "BASE64", "", "hex"])
def test_targets_reject_unknown_alphabet(alphabet: str) -> None:
    with pytest.raises(ValueError, match="alphabet"):
        Base64CodecTarget(alphabet=alphabet)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="alphabet"):
        Base64CodecNodeTarget(alphabet=alphabet)  # type: ignore[arg-type]


def _execute_command(target: CommandTarget, case: bytes) -> object:
    return target.execute(
        case,
        timeout_seconds=5.0,
        max_output_bytes=4096,
        max_total_output_bytes=8192,
    )


def test_python_runtime_identity_is_bound_and_verified_before_input() -> None:
    target = Base64CodecTarget(mode="decode", alphabet="base64")
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
    result = _execute_command(CommandTarget(tuple(argv)), b"Zm9v")

    assert result.exit_code == 3
    assert result.stdout.text == ""
    assert result.stderr.text.strip() == "base64_codec_runtime_identity_mismatch"


def test_node_runtime_identity_is_bound_and_verified_before_input() -> None:
    target = Base64CodecNodeTarget(mode="decode", alphabet="base64")
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
        b"Zm9v",
    )

    assert result.exit_code == 3
    assert result.stdout.text == ""
    assert result.stderr.text.strip() == "base64_codec_runtime_identity_mismatch"


def test_mode_alphabet_and_runtime_identity_change_replay_context() -> None:
    standard_encode = Base64CodecTarget(mode="encode", alphabet="base64").as_command_target()
    standard_decode = Base64CodecTarget(mode="decode", alphabet="base64").as_command_target()
    url_encode = Base64CodecTarget(mode="encode", alphabet="base64url").as_command_target()
    argv = list(standard_encode.argv)
    argv[argv.index("--python-version") + 1] = "__different_python__"
    drifted = CommandTarget(tuple(argv))

    baseline = DifferentialHarness(
        candidate=standard_encode,
        oracle=standard_encode,
    ).replay_context_sha256

    for changed in (standard_decode, url_encode, drifted):
        assert baseline != DifferentialHarness(
            candidate=changed,
            oracle=changed,
        ).replay_context_sha256


def test_node_target_requires_available_runtime() -> None:
    assert shutil.which("node") is not None

    with pytest.raises(ValueError, match="node_executable"):
        Base64CodecNodeTarget(node_executable="")
    with pytest.raises(RuntimeError, match="Node runtime is required"):
        Base64CodecNodeTarget(node_executable="__missing_conformance_node__")
