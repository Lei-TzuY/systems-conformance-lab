import json
import sys

import pytest

from systems_conformance import CommandTarget, DifferentialHarness, load_repro_bundle

ECHO_SCRIPT = "import sys; data=sys.stdin.buffer.read(); sys.stdout.buffer.write(data)"
BUGGY_SCRIPT = (
    "import sys; data=sys.stdin.buffer.read(); "
    "sys.stdout.buffer.write(data.replace(b'BUG', b'BAD'))"
)


def target(script: str) -> CommandTarget:
    return CommandTarget((sys.executable, "-c", script))


def _rewrite_manifest(path, mutate) -> None:
    manifest = json.loads(path.read_text(encoding="utf-8"))
    mutate(manifest)
    path.write_text(json.dumps(manifest), encoding="utf-8")


def test_loader_rejects_same_schema_comparison_semantic_drift(tmp_path) -> None:
    harness = DifferentialHarness(candidate=target(BUGGY_SCRIPT), oracle=target(ECHO_SCRIPT))
    bundle = harness.write_repro(tmp_path / "repro", input_bytes=b"BUG")

    def mutate(manifest: dict[str, object]) -> None:
        comparison = manifest["comparison"]
        assert isinstance(comparison, dict)
        comparison["mismatches"] = ["stderr"]

    _rewrite_manifest(bundle.manifest_path, mutate)

    with pytest.raises(
        ValueError,
        match="comparison does not match candidate/oracle execution evidence",
    ):
        load_repro_bundle(bundle.path)


def test_loader_rejects_same_schema_failure_signature_semantic_drift(tmp_path) -> None:
    harness = DifferentialHarness(candidate=target(BUGGY_SCRIPT), oracle=target(ECHO_SCRIPT))
    bundle = harness.write_repro(tmp_path / "repro", input_bytes=b"BUG")

    def mutate(manifest: dict[str, object]) -> None:
        signature = manifest["failure_signature"]
        assert isinstance(signature, dict)
        signature["dimensions"] = ["stderr"]

    _rewrite_manifest(bundle.manifest_path, mutate)

    with pytest.raises(
        ValueError,
        match="failure signature does not match comparison evidence",
    ):
        load_repro_bundle(bundle.path)


def test_replay_rejects_contradictory_evidence_before_real_target_execution(tmp_path) -> None:
    marker = tmp_path / "executed"
    marker_script = (
        f"from pathlib import Path; Path({str(marker)!r}).write_text('ran'); "
        + BUGGY_SCRIPT
    )
    harness = DifferentialHarness(candidate=target(marker_script), oracle=target(ECHO_SCRIPT))
    bundle = harness.write_repro(tmp_path / "repro", input_bytes=b"BUG")
    assert marker.exists()
    marker.unlink()

    def mutate(manifest: dict[str, object]) -> None:
        comparison = manifest["comparison"]
        assert isinstance(comparison, dict)
        comparison["mismatches"] = ["stderr"]

    _rewrite_manifest(bundle.manifest_path, mutate)

    with pytest.raises(
        ValueError,
        match="comparison does not match candidate/oracle execution evidence",
    ):
        harness.replay_repro(bundle.path)

    assert not marker.exists()
