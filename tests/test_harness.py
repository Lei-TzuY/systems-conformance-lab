import json
import math
import sys

import pytest

from systems_conformance import CommandTarget, DifferentialHarness

ECHO_SCRIPT = (
    "import sys; data = sys.stdin.buffer.read(); sys.stdout.buffer.write(data)"
)
UPPER_SCRIPT = (
    "import sys; data = sys.stdin.buffer.read(); sys.stdout.buffer.write(data.upper())"
)


def target(script: str) -> CommandTarget:
    return CommandTarget((sys.executable, "-c", script))


def test_real_process_targets_match_through_shared_harness() -> None:
    harness = DifferentialHarness(candidate=target(ECHO_SCRIPT), oracle=target(ECHO_SCRIPT))

    result = harness.evaluate(b"binary\x00input\n")

    assert result.comparison.classification == "match"
    assert result.comparison.equivalent is True
    assert result.signature is None
    assert result.candidate.stdout.text == "binary\x00input\n"
    assert result.oracle.stdout.text == "binary\x00input\n"


def test_real_process_mismatch_produces_stable_signature() -> None:
    harness = DifferentialHarness(candidate=target(UPPER_SCRIPT), oracle=target(ECHO_SCRIPT))

    result = harness.evaluate(b"mixed Case")

    assert result.comparison.classification == "product_mismatch"
    assert result.comparison.mismatches == ("stdout",)
    assert result.signature is not None
    assert result.signature.kind == "product_mismatch"
    assert result.signature.dimensions == ("stdout",)
    assert harness.preserves_failure(b"another case", result.signature) is True


def test_harness_classifies_hard_output_budget_as_infrastructure_failure() -> None:
    noisy = target(
        "import sys; chunk=b'x'*65536\n"
        "while True:\n"
        " sys.stdout.buffer.write(chunk); sys.stdout.buffer.flush()"
    )
    harness = DifferentialHarness(
        candidate=noisy,
        oracle=target(ECHO_SCRIPT),
        timeout_seconds=5,
        max_output_bytes=128,
        max_total_output_bytes=128 * 1024,
    )

    result = harness.evaluate(b"input")

    assert result.comparison.classification == "infrastructure_failure"
    assert result.candidate.infrastructure_error is not None
    assert result.candidate.infrastructure_error.startswith("OutputLimitExceeded:")
    assert result.signature is not None
    assert result.signature.kind == "infrastructure_failure"


def test_harness_classifies_invalid_spawn_configuration_as_infrastructure_failure() -> None:
    malformed = CommandTarget((sys.executable, "-c", "pass", "embedded\x00nul"))
    harness = DifferentialHarness(candidate=malformed, oracle=target(ECHO_SCRIPT))

    result = harness.evaluate(b"input")

    assert result.comparison.classification == "infrastructure_failure"
    assert result.candidate.infrastructure_error is not None
    assert result.candidate.infrastructure_error.startswith("ValueError:")
    assert result.oracle.exit_code == 0
    assert result.oracle.infrastructure_error is None
    assert result.signature is not None
    assert result.signature.kind == "infrastructure_failure"


def test_command_target_snapshots_mutable_configuration(tmp_path) -> None:
    argv = [sys.executable, "-c", ECHO_SCRIPT]
    env = {"ONLY": "value"}
    command = CommandTarget(argv, cwd=tmp_path, env=env)

    argv.append("later")
    env["ONLY"] = "changed"

    assert command.argv == (sys.executable, "-c", ECHO_SCRIPT)
    assert command.cwd == str(tmp_path)
    assert command.env == (("ONLY", "value"),)


def test_hard_output_budget_changes_replay_context() -> None:
    command = target(ECHO_SCRIPT)
    baseline = DifferentialHarness(candidate=command, oracle=command)
    constrained = DifferentialHarness(
        candidate=command,
        oracle=command,
        max_total_output_bytes=1024,
    )

    assert baseline.replay_context_sha256 != constrained.replay_context_sha256


def test_input_budget_changes_replay_context() -> None:
    command = target(ECHO_SCRIPT)
    baseline = DifferentialHarness(candidate=command, oracle=command)
    constrained = DifferentialHarness(
        candidate=command,
        oracle=command,
        max_input_bytes=1024,
    )

    assert baseline.replay_context_sha256 != constrained.replay_context_sha256


def test_harness_input_budget_is_enforced_before_real_target_launch(tmp_path) -> None:
    marker = tmp_path / "launched.txt"
    script = (
        "from pathlib import Path; import sys; "
        "Path(sys.argv[1]).write_text('launched'); "
        "data=sys.stdin.buffer.read(); sys.stdout.buffer.write(data)"
    )
    command = CommandTarget((sys.executable, "-c", script, str(marker)))
    harness = DifferentialHarness(
        candidate=command,
        oracle=command,
        max_input_bytes=4,
    )

    result = harness.evaluate(b"1234")
    assert result.comparison.classification == "match"
    assert result.candidate.stdout.text == "1234"
    assert marker.read_text() == "launched"

    marker.unlink()
    with pytest.raises(ValueError, match="stdin exceeds max_input_bytes"):
        harness.evaluate(b"12345")
    assert not marker.exists()


@pytest.mark.parametrize("timeout_seconds", [math.nan, math.inf, -math.inf])
def test_harness_rejects_non_finite_timeout_before_real_target_launch(
    tmp_path, timeout_seconds: float
) -> None:
    marker = tmp_path / "launched.txt"
    command = CommandTarget(
        (
            sys.executable,
            "-c",
            "from pathlib import Path; import sys; Path(sys.argv[1]).write_text('launched')",
            str(marker),
        )
    )

    with pytest.raises(ValueError, match="timeout_seconds must be finite and positive"):
        DifferentialHarness(
            candidate=command,
            oracle=command,
            timeout_seconds=timeout_seconds,
        )
    assert not marker.exists()


def test_replay_rejects_non_standard_json_before_real_target_launch(tmp_path) -> None:
    source = DifferentialHarness(candidate=target(UPPER_SCRIPT), oracle=target(ECHO_SCRIPT))
    bundle = source.write_repro(tmp_path / "case", input_bytes=b"mixed Case")
    manifest = json.loads(bundle.manifest_path.read_text(encoding="utf-8"))
    manifest["metadata"] = {"score": math.nan}
    bundle.manifest_path.write_text(
        json.dumps(manifest, sort_keys=True),
        encoding="utf-8",
    )

    marker = tmp_path / "launched.txt"
    marker_script = (
        "from pathlib import Path; import sys; "
        "Path(sys.argv[1]).write_text('launched'); sys.stdin.buffer.read()"
    )
    command = CommandTarget((sys.executable, "-c", marker_script, str(marker)))
    replay = DifferentialHarness(candidate=command, oracle=command)

    with pytest.raises(ValueError, match="non-finite JSON constant"):
        replay.replay_repro(bundle.path, require_same_context=False)
    assert not marker.exists()


def test_harness_rejects_invalid_execution_limits() -> None:
    command = target(ECHO_SCRIPT)

    with pytest.raises(ValueError, match="timeout_seconds"):
        DifferentialHarness(candidate=command, oracle=command, timeout_seconds=0)
    with pytest.raises(ValueError, match="max_input_bytes"):
        DifferentialHarness(candidate=command, oracle=command, max_input_bytes=-1)
    with pytest.raises(ValueError, match="max_output_bytes"):
        DifferentialHarness(candidate=command, oracle=command, max_output_bytes=-1)
    with pytest.raises(ValueError, match="max_total_output_bytes"):
        DifferentialHarness(candidate=command, oracle=command, max_total_output_bytes=0)
