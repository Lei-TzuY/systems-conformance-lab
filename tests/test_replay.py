import json
import sys

import pytest

from systems_conformance import CommandTarget, DifferentialHarness, load_repro_bundle

ECHO_SCRIPT = (
    "import sys; data = sys.stdin.buffer.read(); sys.stdout.buffer.write(data)"
)
BUGGY_SCRIPT = (
    "import sys; data = sys.stdin.buffer.read(); "
    "sys.stdout.buffer.write(data.replace(b'BUG', b'BAD'))"
)


def target(script: str) -> CommandTarget:
    return CommandTarget((sys.executable, "-c", script))


def test_real_process_repro_round_trip_preserves_failure_identity(tmp_path) -> None:
    harness = DifferentialHarness(candidate=target(BUGGY_SCRIPT), oracle=target(ECHO_SCRIPT))
    observed = harness.evaluate(b"BUG")
    assert observed.signature is not None

    bundle = harness.write_repro(
        tmp_path / "repro",
        input_bytes=b"BUG",
        expected_signature=observed.signature,
        metadata={"source": "replay-integration"},
    )

    replay = harness.replay_repro(bundle.path)

    assert replay.reproduced is True
    assert replay.bundle.input_bytes == b"BUG"
    assert replay.bundle.signature == observed.signature
    assert replay.bundle.metadata == {"source": "replay-integration"}
    assert replay.run.comparison.classification == "product_mismatch"


def test_replay_reports_signature_drift_without_relabeling_it(tmp_path) -> None:
    original = DifferentialHarness(candidate=target(BUGGY_SCRIPT), oracle=target(ECHO_SCRIPT))
    bundle = original.write_repro(tmp_path / "repro", input_bytes=b"BUG")

    fixed = DifferentialHarness(candidate=target(ECHO_SCRIPT), oracle=target(ECHO_SCRIPT))
    replay = fixed.replay_repro(bundle.path)

    assert replay.reproduced is False
    assert replay.run.comparison.classification == "match"
    assert replay.run.signature is None
    assert replay.bundle.signature.kind == "product_mismatch"


def test_loader_rejects_manifest_input_path_escape_before_execution(tmp_path) -> None:
    harness = DifferentialHarness(candidate=target(BUGGY_SCRIPT), oracle=target(ECHO_SCRIPT))
    bundle = harness.write_repro(tmp_path / "repro", input_bytes=b"BUG")
    manifest = json.loads(bundle.manifest_path.read_text(encoding="utf-8"))
    manifest["input"]["path"] = "../outside.bin"
    bundle.manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ValueError, match="direct child input.bin"):
        load_repro_bundle(bundle.path)


def test_loader_enforces_input_budget_from_manifest(tmp_path) -> None:
    harness = DifferentialHarness(candidate=target(BUGGY_SCRIPT), oracle=target(ECHO_SCRIPT))
    bundle = harness.write_repro(tmp_path / "repro", input_bytes=b"BUG")

    with pytest.raises(ValueError, match="max_input_bytes"):
        load_repro_bundle(bundle.path, max_input_bytes=2)


def test_loader_rejects_invalid_failure_signature_schema(tmp_path) -> None:
    harness = DifferentialHarness(candidate=target(BUGGY_SCRIPT), oracle=target(ECHO_SCRIPT))
    bundle = harness.write_repro(tmp_path / "repro", input_bytes=b"BUG")
    manifest = json.loads(bundle.manifest_path.read_text(encoding="utf-8"))
    manifest["failure_signature"]["schema_version"] = "unknown"
    bundle.manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ValueError, match="failure signature schema"):
        load_repro_bundle(bundle.path)


def test_loader_rejects_declared_input_size_mismatch(tmp_path) -> None:
    harness = DifferentialHarness(candidate=target(BUGGY_SCRIPT), oracle=target(ECHO_SCRIPT))
    bundle = harness.write_repro(tmp_path / "repro", input_bytes=b"BUG")
    manifest = json.loads(bundle.manifest_path.read_text(encoding="utf-8"))
    manifest["input"]["size_bytes"] = 99
    bundle.manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ValueError, match="does not match manifest"):
        load_repro_bundle(bundle.path)
