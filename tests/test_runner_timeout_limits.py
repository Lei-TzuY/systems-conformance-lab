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


@pytest.mark.parametrize("timeout_seconds", [True, False, "1"])
def test_invalid_timeout_type_is_rejected_before_target_launch(
    tmp_path: Path, timeout_seconds: object
) -> None:
    marker = tmp_path / "executed"

    with pytest.raises(TypeError, match="timeout_seconds must be a finite positive number"):
        run_process(
            python(
                "from pathlib import Path; import sys; Path(sys.argv[1]).write_text('ran')",
                str(marker),
            ),
            timeout_seconds=timeout_seconds,  # type: ignore[arg-type]
        )

    assert not marker.exists()


@pytest.mark.parametrize("timeout_seconds", [1, 0.25])
def test_positive_numeric_timeout_executes_real_target(timeout_seconds: float) -> None:
    result = run_process(
        python("import sys; sys.stdout.write('ok')"),
        timeout_seconds=timeout_seconds,
    )

    assert result.exit_code == 0
    assert result.timed_out is False
    assert result.infrastructure_error is None
    assert result.stdout.text == "ok"
