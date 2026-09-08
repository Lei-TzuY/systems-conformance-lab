from __future__ import annotations

import sys
from pathlib import Path

import pytest

from systems_conformance.runner import run_process


@pytest.mark.parametrize(
    "argv",
    [
        sys.executable,
        [sys.executable, 1],
        [sys.executable, None],
    ],
)
def test_run_process_rejects_non_string_argv_before_launch(argv: object) -> None:
    with pytest.raises(TypeError, match="argv must be a sequence of strings"):
        run_process(argv)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "env",
    [
        {1: "value"},
        {"KEY": 1},
        {"KEY": None},
    ],
)
def test_run_process_rejects_non_string_environment_before_launch(env: object) -> None:
    with pytest.raises(TypeError, match="env keys and values must be strings"):
        run_process([sys.executable, "-c", "raise SystemExit(99)"], env=env)  # type: ignore[arg-type]


def test_invalid_environment_cannot_launch_real_child(tmp_path: Path) -> None:
    marker = tmp_path / "launched"
    code = "from pathlib import Path; import sys; Path(sys.argv[1]).write_text('launched')"

    with pytest.raises(TypeError, match="env keys and values must be strings"):
        run_process(
            [sys.executable, "-c", code, str(marker)],
            env={"VALID": object()},  # type: ignore[dict-item]
        )

    assert not marker.exists()


def test_valid_string_environment_still_launches_real_child(tmp_path: Path) -> None:
    marker = tmp_path / "launched"
    code = (
        "from pathlib import Path; import os, sys; "
        "Path(sys.argv[1]).write_text(os.environ['CONFORMANCE_MARKER'])"
    )

    result = run_process(
        [sys.executable, "-c", code, str(marker)],
        env={"CONFORMANCE_MARKER": "ok"},
    )

    assert result.infrastructure_error is None
    assert result.exit_code == 0
    assert marker.read_text() == "ok"
