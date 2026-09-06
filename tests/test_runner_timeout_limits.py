from __future__ import annotations

import sys
from pathlib import Path

import pytest

from systems_conformance import run_process


def python(*args: str) -> list[str]:
    return [sys.executable, "-c", *args]


@pytest.mark.parametrize("timeout_seconds", [float("nan"), float("inf"), float("-inf")])
def test_rejects_non_finite_timeout(timeout_seconds: float) -> None:
    with pytest.raises(ValueError, match="timeout_seconds must be finite and positive"):
        run_process(python("pass"), timeout_seconds=timeout_seconds)


def test_non_finite_timeout_is_rejected_before_target_launch(tmp_path: Path) -> None:
    marker = tmp_path / "executed"

    with pytest.raises(ValueError, match="timeout_seconds must be finite and positive"):
        run_process(
            python(
                "from pathlib import Path; import sys; Path(sys.argv[1]).write_text('ran')",
                str(marker),
            ),
            timeout_seconds=float("nan"),
        )

    assert not marker.exists()
