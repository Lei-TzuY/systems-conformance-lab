import json
import sys

import pytest

from systems_conformance import CommandTarget, DifferentialHarness
from systems_conformance.repro_evidence import (
    load_evidenced_repro_bundle,
    validate_failure_model_evidence,
)

ECHO_SCRIPT = "import sys; data=sys.stdin.buffer.read(); sys.stdout.buffer.write(data)"
BUGGY_SCRIPT = (
    "import sys; data=sys.stdin.buffer.read(); "
    "sys.stdout.buffer.write(data.replace(b'BUG', b'BAD'))"
)


def _target(script: str) -> CommandTarget:
    return CommandTarget((sys.executable, "-c", script))


def test_process_kill_evidence_is_typed_and_bounded() -> None:
    evidence = validate_failure_model_evidence(
        {
            "failure_model": "process-kill-same-mount",
            "remount_performed": False,
            "power_loss_recovery_proven": False,
        }
    )

    assert evidence is not None
    assert evidence.failure_model == "process-kill-same-mount"
    assert not evidence.remount_performed
    assert not evidence.power_loss_recovery_proven


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("remount_performed", True, "cannot claim a remount"),
        ("power_loss_recovery_proven", True, "cannot claim power-loss recovery"),
    ],
)
def test_process_kill_evidence_rejects_claim_upgrades(field, value, message) -> None:
    metadata = {
        "failure_model": "process-kill-same-mount",
        "remount_performed": False,
        "power_loss_recovery_proven": False,
    }
    metadata[field] = value

    with pytest.raises(ValueError, match=message):
        validate_failure_model_evidence(metadata)


def test_partial_failure_model_evidence_fails_closed() -> None:
    with pytest.raises(ValueError, match="incomplete failure-model evidence"):
        validate_failure_model_evidence({"failure_model": "process-kill-same-mount"})


def test_real_repro_round_trip_preserves_validated_failure_model_evidence(tmp_path) -> None:
    harness = DifferentialHarness(candidate=_target(BUGGY_SCRIPT), oracle=_target(ECHO_SCRIPT))
    observed = harness.evaluate(b"BUG")
    assert observed.signature is not None
    metadata = {
        "failure_model": "process-kill-same-mount",
        "remount_performed": False,
        "power_loss_recovery_proven": False,
        "source": "durable-publish",
    }
    bundle = harness.write_repro(
        tmp_path / "repro",
        input_bytes=b"BUG",
        expected_signature=observed.signature,
        metadata=metadata,
    )

    loaded = load_evidenced_repro_bundle(bundle.path)

    assert loaded.metadata == metadata


def test_tampered_repro_evidence_is_rejected_before_target_execution(tmp_path) -> None:
    marker = tmp_path / "executed"
    marker_script = (
        f"from pathlib import Path; Path({str(marker)!r}).write_text('ran'); " + BUGGY_SCRIPT
    )
    harness = DifferentialHarness(candidate=_target(marker_script), oracle=_target(ECHO_SCRIPT))
    bundle = harness.write_repro(
        tmp_path / "repro",
        input_bytes=b"BUG",
        metadata={
            "failure_model": "process-kill-same-mount",
            "remount_performed": False,
            "power_loss_recovery_proven": False,
        },
    )
    assert marker.exists()
    marker.unlink()

    manifest = json.loads(bundle.manifest_path.read_text(encoding="utf-8"))
    manifest["metadata"]["power_loss_recovery_proven"] = True
    bundle.manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ValueError, match="cannot claim power-loss recovery"):
        load_evidenced_repro_bundle(bundle.path)

    assert not marker.exists()
