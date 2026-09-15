from __future__ import annotations

import json
import os

from systems_conformance.durable_publish_crash_adapter import DurablePublishCrashTarget
from systems_conformance.harness import DifferentialHarness


def _execute(target: DurablePublishCrashTarget, case: bytes = b""):
    return target.as_command_target().execute(
        case,
        timeout_seconds=6.0,
        max_output_bytes=4096,
        max_total_output_bytes=8192,
    )


def test_durable_publish_exposes_directory_sync_crash_boundaries() -> None:
    result = _execute(DurablePublishCrashTarget())

    assert result.infrastructure_error is None
    assert result.exit_code == 0, result.stderr.text
    assert result.stderr.text == ""
    payload = json.loads(result.stdout.text)
    if os.name == "nt":
        assert payload == {
            "supported": False,
            "reason": "directory fsync unavailable",
            "failure_model": "process-kill-same-mount",
            "power_loss_recovery_proven": False,
            "remount_performed": False,
        }
        return

    assert payload == {
        "supported": True,
        "failure_model": "process-kill-same-mount",
        "power_loss_recovery_proven": False,
        "remount_performed": False,
        "initial_value": "generation-0",
        "pre_dirsync_replace_completed": True,
        "pre_dirsync_writer_forced_crash": True,
        "value_after_pre_dirsync_crash": "generation-1",
        "pre_dirsync_staging_absent": True,
        "injected_directory_sync_errno": "EIO",
        "value_after_directory_sync_failure": "generation-2",
        "directory_sync_failure_staging_absent": True,
        "completed_publish_returned": True,
        "post_publish_writer_forced_crash": True,
        "value_after_completed_publish_crash": "generation-3",
        "completed_publish_staging_absent": True,
    }


def test_durable_publish_crash_target_rejects_nonempty_input() -> None:
    result = _execute(DurablePublishCrashTarget(), b"untrusted input")

    assert result.infrastructure_error is None
    assert result.exit_code == 2
    assert result.stdout.text == ""
    assert (
        result.stderr.text.strip()
        == "protocol_error: durable publish crash target requires empty input"
    )


def test_real_harness_repeats_durable_publish_crash_contract_deterministically() -> None:
    target = DurablePublishCrashTarget()
    harness = DifferentialHarness(
        candidate=target.as_command_target(),
        oracle=target.as_command_target(),
        timeout_seconds=6.0,
    )

    run = harness.evaluate(b"")

    assert run.candidate.exit_code == 0, run.candidate.stderr.text
    assert run.oracle.exit_code == 0, run.oracle.stderr.text
    assert run.comparison.equivalent is True
    assert run.comparison.classification == "match"
