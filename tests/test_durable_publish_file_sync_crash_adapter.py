from __future__ import annotations

import json
import os

from systems_conformance.durable_publish_file_sync_crash_adapter import (
    DurablePublishFileSyncCrashTarget,
)
from systems_conformance.harness import DifferentialHarness


def _execute(target: DurablePublishFileSyncCrashTarget, case: bytes = b""):
    return target.as_command_target().execute(
        case,
        timeout_seconds=6.0,
        max_output_bytes=4096,
        max_total_output_bytes=8192,
    )


def test_durable_publish_exposes_file_sync_crash_boundaries() -> None:
    result = _execute(DurablePublishFileSyncCrashTarget())

    assert result.infrastructure_error is None
    assert result.exit_code == 0, result.stderr.text
    assert result.stderr.text == ""
    payload = json.loads(result.stdout.text)
    if os.name == "nt":
        assert payload == {"supported": False, "reason": "directory fsync unavailable"}
        return

    assert payload == {
        "supported": True,
        "initial_value": "generation-0",
        "pre_replace_writer_forced_crash": True,
        "value_after_pre_replace_crash": "generation-0",
        "crashed_staging_preserved": True,
        "crashed_staging_value": "generation-1",
        "injected_file_sync_errno": "EIO",
        "file_sync_failure_destination_unchanged": True,
        "file_sync_failure_staging_preserved": True,
        "recovery_publish_value": "generation-3",
        "recovery_staging_absent": True,
    }


def test_durable_publish_file_sync_crash_target_rejects_nonempty_input() -> None:
    result = _execute(DurablePublishFileSyncCrashTarget(), b"untrusted input")

    assert result.infrastructure_error is None
    assert result.exit_code == 2
    assert result.stdout.text == ""
    assert result.stderr.text.strip() == (
        "protocol_error: durable publish file-sync crash target requires empty input"
    )


def test_real_harness_repeats_file_sync_crash_contract_deterministically() -> None:
    target = DurablePublishFileSyncCrashTarget()
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
