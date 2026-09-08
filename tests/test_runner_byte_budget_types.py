from __future__ import annotations

import sys
from pathlib import Path

import pytest

from systems_conformance import CommandTarget, DifferentialHarness, run_process


def marker_command(marker: Path) -> list[str]:
    return [
        sys.executable,
        "-c",
        "from pathlib import Path; import sys; Path(sys.argv[1]).write_text('ran')",
        str(marker),
    ]


@pytest.mark.parametrize(
    ("limit_name", "invalid_value"),
    [
        ("max_input_bytes", True),
        ("max_input_bytes", 1.5),
        ("max_output_bytes", True),
        ("max_output_bytes", 1.5),
        ("max_total_output_bytes", True),
        ("max_total_output_bytes", 1.5),
    ],
)
def test_run_process_rejects_noninteger_byte_budgets_before_launch(
    tmp_path: Path, limit_name: str, invalid_value: object
) -> None:
    marker = tmp_path / "launched.txt"

    with pytest.raises(TypeError, match=f"{limit_name} must be"):
        run_process(marker_command(marker), **{limit_name: invalid_value})

    assert not marker.exists()


@pytest.mark.parametrize(
    ("limit_name", "invalid_value"),
    [
        ("max_input_bytes", False),
        ("max_input_bytes", 4.0),
        ("max_output_bytes", False),
        ("max_output_bytes", 4.0),
        ("max_total_output_bytes", True),
        ("max_total_output_bytes", 4.0),
    ],
)
def test_harness_rejects_noninteger_byte_budgets_before_context_or_execution(
    limit_name: str, invalid_value: object
) -> None:
    command = CommandTarget((sys.executable, "-c", "pass"))

    with pytest.raises(TypeError, match=f"{limit_name} must be"):
        DifferentialHarness(
            candidate=command,
            oracle=command,
            **{limit_name: invalid_value},
        )


def test_integer_byte_budget_boundary_values_still_execute_real_target(tmp_path: Path) -> None:
    marker = tmp_path / "launched.txt"
    command = marker_command(marker)

    result = run_process(
        command,
        max_input_bytes=0,
        max_output_bytes=0,
        max_total_output_bytes=1,
    )

    assert result.exit_code == 0
    assert result.infrastructure_error is None
    assert marker.read_text() == "ran"
