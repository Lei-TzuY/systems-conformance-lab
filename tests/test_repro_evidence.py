import json
import sys

import pytest

from systems_conformance import CommandTarget, DifferentialHarness
from systems_conformance.repro_evidence import (
    REDUCTION_EVIDENCE_METADATA_KEY,
    REDUCTION_EVIDENCE_SCHEMA_VERSION,
    load_evidenced_repro_bundle,
    validate_failure_model_evidence,
    validate_reduction_evidence,
)

ECHO_SCRIPT = "import sys; data=sys.stdin.buffer.read(); sys.stdout.buffer.write(data)"
BUGGY_SCRIPT = (
    "import sys; data=sys.stdin.buffer.read(); "
    "sys.stdout.buffer.write(data.replace(b'BUG', b'BAD'))"
)


def _target(script: str) -> CommandTarget:
    return CommandTarget((sys.executable, "-c", script))


def _reduction_metadata(**overrides):
    evidence = {
        "schema_version": REDUCTION_EVIDENCE_SCHEMA_VERSION,
        "evaluations": 4,
        "candidate_visits": 5,
        "accepted_steps": 2,
        "exhausted_budget": False,
        "termination_reason": "fixed_point",
    }
    evidence.update(overrides)
    return {REDUCTION_EVIDENCE_METADATA_KEY: evidence}


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


def test_reduction_evidence_is_typed_and_semantically_bounded() -> None:
    evidence = validate_reduction_evidence(_reduction_metadata())

    assert evidence is not None
    assert evidence.evaluations == 4
    assert evidence.candidate_visits == 5
    assert evidence.accepted_steps == 2
    assert not evidence.exhausted_budget
    assert evidence.termination_reason == "fixed_point"


@pytest.mark.parametrize(
    ("overrides", "error", "message"),
    [
        ({"evaluations": True}, TypeError, "evaluations must be an integer"),
        ({"candidate_visits": -1}, ValueError, "candidate_visits must be non-negative"),
        (
            {"evaluations": 4, "candidate_visits": 2, "accepted_steps": 1},
            ValueError,
            "candidate_visits cannot be fewer than evaluated candidates",
        ),
        ({"accepted_steps": 4}, ValueError, "accepted_steps exceeds evaluated candidates"),
        (
            {"exhausted_budget": True, "termination_reason": "fixed_point"},
            ValueError,
            "termination_reason contradicts exhausted_budget",
        ),
    ],
)
def test_reduction_evidence_rejects_malformed_or_contradictory_work_records(
    overrides, error, message
) -> None:
    with pytest.raises(error, match=message):
        validate_reduction_evidence(_reduction_metadata(**overrides))


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


def test_real_repro_round_trip_preserves_validated_reduction_evidence(tmp_path) -> None:
    harness = DifferentialHarness(candidate=_target(BUGGY_SCRIPT), oracle=_target(ECHO_SCRIPT))
    bundle = harness.write_repro(
        tmp_path / "repro",
        input_bytes=b"BUG",
        metadata={**_reduction_metadata(), "source": "reducer"},
    )

    loaded = load_evidenced_repro_bundle(bundle.path)

    assert loaded.metadata[REDUCTION_EVIDENCE_METADATA_KEY]["termination_reason"] == "fixed_point"
    replay = harness.replay_repro(bundle.path)
    assert replay.reproduced


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
        harness.replay_repro(bundle.path)

    assert not marker.exists()


def test_tampered_reduction_evidence_is_rejected_before_target_execution(tmp_path) -> None:
    marker = tmp_path / "executed"
    marker_script = (
        f"from pathlib import Path; Path({str(marker)!r}).write_text('ran'); " + BUGGY_SCRIPT
    )
    harness = DifferentialHarness(candidate=_target(marker_script), oracle=_target(ECHO_SCRIPT))
    bundle = harness.write_repro(
        tmp_path / "repro",
        input_bytes=b"BUG",
        metadata=_reduction_metadata(),
    )
    assert marker.exists()
    marker.unlink()

    manifest = json.loads(bundle.manifest_path.read_text(encoding="utf-8"))
    manifest["metadata"][REDUCTION_EVIDENCE_METADATA_KEY]["exhausted_budget"] = True
    bundle.manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ValueError, match="termination_reason contradicts exhausted_budget"):
        harness.replay_repro(bundle.path)

    assert not marker.exists()


def test_impossible_reducer_visit_evidence_is_rejected_before_target_execution(tmp_path) -> None:
    marker = tmp_path / "executed"
    marker_script = (
        f"from pathlib import Path; Path({str(marker)!r}).write_text('ran'); " + BUGGY_SCRIPT
    )
    harness = DifferentialHarness(candidate=_target(marker_script), oracle=_target(ECHO_SCRIPT))
    bundle = harness.write_repro(
        tmp_path / "repro",
        input_bytes=b"BUG",
        metadata=_reduction_metadata(),
    )
    assert marker.exists()
    marker.unlink()

    manifest = json.loads(bundle.manifest_path.read_text(encoding="utf-8"))
    evidence = manifest["metadata"][REDUCTION_EVIDENCE_METADATA_KEY]
    evidence["evaluations"] = 5
    evidence["candidate_visits"] = 2
    evidence["accepted_steps"] = 1
    bundle.manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ValueError, match="candidate_visits cannot be fewer than evaluated candidates"):
        harness.replay_repro(bundle.path)

    assert not marker.exists()
