from __future__ import annotations

import sys
from pathlib import Path

import pytest

from systems_conformance import CommandTarget, DifferentialHarness


def _target(marker: Path) -> CommandTarget:
    return CommandTarget(
        (
            sys.executable,
            "-c",
            "from pathlib import Path; import sys; Path(sys.argv[1]).write_text('ran')",
            str(marker),
        )
    )


@pytest.mark.parametrize("timeout_seconds", [True, False, "1"])
def test_harness_rejects_invalid_timeout_type_before_target_launch(
    tmp_path: Path, timeout_seconds: object
) -> None:
    marker = tmp_path / "executed"
    command = _target(marker)

    with pytest.raises(TypeError, match="timeout_seconds must be a finite positive number"):
        DifferentialHarness(
            candidate=command,
            oracle=command,
            timeout_seconds=timeout_seconds,  # type: ignore[arg-type]
        )

    assert not marker.exists()


def test_harness_accepts_integer_timeout_and_executes_real_targets(tmp_path: Path) -> None:
    marker = tmp_path / "executed"
    command = _target(marker)
    harness = DifferentialHarness(candidate=command, oracle=command, timeout_seconds=1)

    result = harness.evaluate(b"")

    assert result.comparison.classification == "match"
    assert marker.read_text() == "ran"
