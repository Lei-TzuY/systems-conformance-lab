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


def test_loader_rejects_comparison_record_field_drift(tmp_path) -> None:
    harness = DifferentialHarness(candidate=target(BUGGY_SCRIPT), oracle=target(ECHO_SCRIPT))
    bundle = harness.write_repro(tmp_path / "repro", input_bytes=b"BUG")
    manifest = json.loads(bundle.manifest_path.read_text(encoding="utf-8"))
    manifest["comparison"]["future_equivalence_detail"] = "not-v1"
    del manifest["comparison"]["mismatches"]
    bundle.manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(
        ValueError, match="repro comparison record fields do not match v1 schema"
    ) as exc_info:
        load_repro_bundle(bundle.path)

    error = str(exc_info.value)
    assert "future_equivalence_detail" in error
    assert "mismatches" in error


def test_loader_rejects_comparison_schema_version_drift(tmp_path) -> None:
    harness = DifferentialHarness(candidate=target(BUGGY_SCRIPT), oracle=target(ECHO_SCRIPT))
    bundle = harness.write_repro(tmp_path / "repro", input_bytes=b"BUG")
    manifest = json.loads(bundle.manifest_path.read_text(encoding="utf-8"))
    manifest["comparison"]["schema_version"] = "systems-conformance.comparison.v2"
    bundle.manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ValueError, match="unsupported repro comparison schema"):
        load_repro_bundle(bundle.path)


def test_replay_rejects_comparison_schema_drift_before_real_target_execution(tmp_path) -> None:
    marker = tmp_path / "executed"
    marker_script = (
        f"from pathlib import Path; Path({str(marker)!r}).write_text('ran'); "
        + BUGGY_SCRIPT
    )
    harness = DifferentialHarness(candidate=target(marker_script), oracle=target(ECHO_SCRIPT))
    bundle = harness.write_repro(tmp_path / "repro", input_bytes=b"BUG")
    assert marker.exists()
    marker.unlink()

    manifest = json.loads(bundle.manifest_path.read_text(encoding="utf-8"))
    manifest["comparison"]["future_classification_semantics"] = "must-not-run"
    bundle.manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(
        ValueError, match="repro comparison record fields do not match v1 schema"
    ):
        harness.replay_repro(bundle.path)

    assert not marker.exists()
