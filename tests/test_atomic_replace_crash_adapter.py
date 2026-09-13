from __future__ import annotations

import json

from systems_conformance.atomic_replace_crash_adapter import AtomicReplaceCrashTarget
from systems_conformance.harness import DifferentialHarness


def _execute(target: AtomicReplaceCrashTarget, case: bytes = b""):
    return target.as_command_target().execute(
        case,
        timeout_seconds=6.0,
        max_output_bytes=4096,
        max_total_output_bytes=8192,
    )


def test_atomic_replace_preserves_complete_generations_across_writer_crashes() -> None:
    result = _execute(AtomicReplaceCrashTarget())

    assert result.infrastructure_error is None
    assert result.exit_code == 0, result.stderr.text
    assert result.stderr.text == ""
    assert json.loads(result.stdout.text) == {
        "initial_value": "generation-0",
        "pre_publish_staging_synced": True,
        "pre_publish_writer_forced_crash": True,
        "value_after_pre_publish_crash": "generation-0",
        "pre_publish_staging_survived": True,
        "post_publish_staging_synced": True,
        "post_publish_replace_completed": True,
        "post_publish_writer_forced_crash": True,
        "value_after_post_publish_crash": "generation-2",
        "post_publish_staging_absent": True,
        "injected_replace_errno": "EIO",
        "value_after_injected_replace_failure": "generation-2",
        "fault_staging_preserved": True,
        "followup_value": "generation-4",
        "followup_staging_absent": True,
    }


def test_atomic_replace_crash_target_rejects_nonempty_input() -> None:
    result = _execute(AtomicReplaceCrashTarget(), b"untrusted input")

    assert result.infrastructure_error is None
    assert result.exit_code == 2
    assert result.stdout.text == ""
    assert (
        result.stderr.text.strip()
        == "protocol_error: atomic replace crash target requires empty input"
    )


def test_real_harness_repeats_atomic_replace_crash_contract_deterministically() -> None:
    target = AtomicReplaceCrashTarget()
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
