from __future__ import annotations

import json
import os
import sys

import pytest

from systems_conformance import run_process


def python(*args: str) -> list[str]:
    return [sys.executable, "-c", *args]


def test_captures_stdout_stderr_and_exit_code() -> None:
    result = run_process(
        python("import sys; print('out'); print('err', file=sys.stderr); raise SystemExit(7)")
    )

    assert result.exit_code == 7
    assert result.signal is None
    assert result.timed_out is False
    assert result.infrastructure_error is None
    assert result.stdout.text == f"out{os.linesep}"
    assert result.stderr.text == f"err{os.linesep}"


def test_argv_is_not_interpreted_by_a_shell() -> None:
    payload = "hello; echo SHOULD_NOT_RUN"
    result = run_process(
        [sys.executable, "-c", "import sys; print(sys.argv[1])", payload]
    )

    assert result.exit_code == 0
    assert result.stdout.text == payload + os.linesep


def test_timeout_is_classified() -> None:
    result = run_process(
        python("import time; time.sleep(30)"),
        timeout_seconds=0.05,
    )

    assert result.timed_out is True
    assert result.infrastructure_error is None
    if os.name == "posix":
        assert result.signal is not None


def test_output_capture_is_bounded_but_reports_total_size() -> None:
    result = run_process(
        python("import sys; sys.stdout.write('x' * 4096)"),
        max_output_bytes=128,
    )

    assert result.exit_code == 0
    assert result.stdout.text == "x" * 128
    assert result.stdout.total_bytes == 4096
    assert result.stdout.truncated is True


def test_missing_executable_is_infrastructure_error() -> None:
    result = run_process(["definitely-not-a-real-systems-conformance-command"])

    assert result.exit_code is None
    assert result.infrastructure_error is not None
    assert result.timed_out is False


def test_result_is_json_serializable_and_versioned() -> None:
    result = run_process(python("print('ok')"))
    encoded = json.dumps(result.to_dict(), sort_keys=True)

    assert "systems-conformance.execution.v1" in encoded
    assert '"argv"' in encoded


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"timeout_seconds": 0}, "timeout_seconds"),
        ({"max_output_bytes": -1}, "max_output_bytes"),
    ],
)
def test_rejects_invalid_limits(kwargs: dict[str, object], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        run_process(python("pass"), **kwargs)


def test_rejects_empty_argv() -> None:
    with pytest.raises(ValueError, match="argv"):
        run_process([])
