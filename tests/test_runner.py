from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

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
    result = run_process([sys.executable, "-c", "import sys; print(sys.argv[1])", payload])
    assert result.exit_code == 0
    assert result.stdout.text == payload + os.linesep


def test_timeout_is_classified() -> None:
    result = run_process(python("import time; time.sleep(30)"), timeout_seconds=0.05)
    assert result.timed_out is True
    assert result.infrastructure_error is None
    if os.name == "posix":
        assert result.signal is not None


def test_input_at_budget_is_delivered_intact() -> None:
    payload = b"bounded-input"
    result = run_process(
        python("import sys; data=sys.stdin.buffer.read(); sys.stdout.buffer.write(data)"),
        stdin=payload,
        max_input_bytes=len(payload),
    )
    assert result.exit_code == 0
    assert result.infrastructure_error is None
    assert result.stdout.text == payload.decode()


def test_oversized_input_is_rejected_before_target_executes(tmp_path: Path) -> None:
    marker = tmp_path / "executed"
    with pytest.raises(ValueError, match="stdin exceeds max_input_bytes"):
        run_process(
            python("from pathlib import Path; import sys; Path(sys.argv[1]).write_text('ran')", str(marker)),
            stdin=b"12345",
            max_input_bytes=4,
        )
    assert not marker.exists()


def test_output_capture_is_bounded_but_reports_total_size() -> None:
    result = run_process(python("import sys; sys.stdout.write('x' * 4096)"), max_output_bytes=128)
    assert result.exit_code == 0
    assert result.stdout.text == "x" * 128
    assert result.stdout.total_bytes == 4096
    assert result.stdout.truncated is True


def test_hard_output_budget_stops_untrusted_output() -> None:
    result = run_process(
        python("import sys\nchunk = b'x' * 65536\nwhile True:\n    sys.stdout.buffer.write(chunk)\n    sys.stdout.buffer.flush()\n"),
        timeout_seconds=5,
        max_output_bytes=128,
        max_total_output_bytes=128 * 1024,
    )
    assert result.timed_out is False
    assert result.infrastructure_error is not None
    assert result.infrastructure_error.startswith("OutputLimitExceeded:")
    assert len(result.stdout.text.encode()) <= 128
    assert result.stdout.total_bytes > 128 * 1024
    assert result.stdout.truncated is True


def test_hard_output_budget_counts_stdout_and_stderr_together() -> None:
    result = run_process(
        python("import sys\nsys.stdout.buffer.write(b'o' * 70000)\nsys.stdout.buffer.flush()\nsys.stderr.buffer.write(b'e' * 70000)\nsys.stderr.buffer.flush()\nimport time; time.sleep(30)\n"),
        timeout_seconds=5,
        max_output_bytes=64,
        max_total_output_bytes=128 * 1024,
    )
    assert result.timed_out is False
    assert result.infrastructure_error is not None
    assert result.infrastructure_error.startswith("OutputLimitExceeded:")
    assert result.stdout.total_bytes + result.stderr.total_bytes > 128 * 1024


def test_post_exit_descendant_pipe_leak_is_bounded() -> None:
    started = time.monotonic()
    result = run_process(
        python("import subprocess, sys\nsubprocess.Popen([sys.executable, '-c', 'import time; time.sleep(2)'])\nprint('root done')\n"),
        timeout_seconds=5,
    )
    elapsed = time.monotonic() - started
    assert elapsed < 1.5
    assert result.exit_code == 0
    assert result.timed_out is False
    assert result.infrastructure_error is not None
    assert result.infrastructure_error.startswith("ProcessTreeLeak:")
    assert result.stdout.text == f"root done{os.linesep}"


@pytest.mark.skipif(os.name != "posix", reason="POSIX process-group cleanup contract")
def test_post_exit_descendant_cannot_escape_by_detaching_stdio(tmp_path: Path) -> None:
    marker = tmp_path / "escaped"
    child = (
        "import pathlib, sys, time; "
        "time.sleep(0.35); pathlib.Path(sys.argv[1]).write_text('escaped')"
    )
    root = (
        "import subprocess, sys; "
        "subprocess.Popen([sys.executable, '-c', sys.argv[1], sys.argv[2]], "
        "stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)"
    )

    result = run_process(python(root, child, str(marker)), timeout_seconds=2)

    assert result.exit_code == 0
    assert result.timed_out is False
    assert result.infrastructure_error is not None
    assert result.infrastructure_error.startswith("ProcessTreeLeak:")
    time.sleep(0.5)
    assert not marker.exists()


def test_missing_executable_is_infrastructure_error() -> None:
    result = run_process(["definitely-not-a-real-systems-conformance-command"])
    assert result.exit_code is None
    assert result.infrastructure_error is not None
    assert result.timed_out is False


def test_invalid_spawn_argv_is_structured_infrastructure_error() -> None:
    result = run_process([sys.executable, "-c", "pass", "embedded\x00nul"])

    assert result.exit_code is None
    assert result.signal is None
    assert result.timed_out is False
    assert result.infrastructure_error is not None
    assert result.infrastructure_error.startswith("ValueError:")
    assert result.stdout.total_bytes == 0
    assert result.stderr.total_bytes == 0


def test_result_is_json_serializable_and_versioned() -> None:
    result = run_process(python("print('ok')"))
    encoded = json.dumps(result.to_dict(), sort_keys=True)
    assert "systems-conformance.execution.v1" in encoded
    assert '"argv"' in encoded


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"timeout_seconds": 0}, "timeout_seconds"),
        ({"max_input_bytes": -1}, "max_input_bytes"),
        ({"max_output_bytes": -1}, "max_output_bytes"),
        ({"max_total_output_bytes": 0}, "max_total_output_bytes"),
    ],
)
def test_rejects_invalid_limits(kwargs: dict[str, object], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        run_process(python("pass"), **kwargs)


def test_rejects_empty_argv() -> None:
    with pytest.raises(ValueError, match="argv"):
        run_process([])


class _ChangingArgv:
    def __init__(self, first: tuple[str, ...], later: tuple[object, ...]) -> None:
        self.first = first
        self.later = later
        self.reads = 0

    def __iter__(self):
        self.reads += 1
        return iter(self.first if self.reads == 1 else self.later)


class _SplitEnvironment:
    def __init__(self) -> None:
        self.values = dict(os.environ)
        self.values["CONFORMANCE_SNAPSHOT"] = "validated"
        self.item_reads = 0

    def items(self):
        self.item_reads += 1
        return self.values.items()

    def keys(self):
        return self.values.keys()

    def __getitem__(self, key: str) -> str:
        if key == "CONFORMANCE_SNAPSHOT":
            return "changed-after-validation"
        return self.values[key]


def test_runner_snapshots_argv_once_before_validation() -> None:
    script = "print('single-snapshot')"
    argv = _ChangingArgv(
        (sys.executable, "-c", script),
        (sys.executable, "-c", script, 7),
    )

    result = run_process(argv)

    assert argv.reads == 1
    assert result.exit_code == 0
    assert result.infrastructure_error is None
    assert result.stdout.text.splitlines() == ["single-snapshot"]


def test_runner_executes_same_environment_snapshot_it_validated() -> None:
    env = _SplitEnvironment()

    result = run_process(
        python("import os; print(os.environ['CONFORMANCE_SNAPSHOT'])"),
        env=env,
    )

    assert env.item_reads == 1
    assert result.exit_code == 0
    assert result.infrastructure_error is None
    assert result.stdout.text.splitlines() == ["validated"]
