from __future__ import annotations

import os
import subprocess
import sys
import time

import systems_conformance.runner as runner_module
from systems_conformance import run_process


class _DelayedReapProcess:
    def __init__(self) -> None:
        self.returncode: int | None = None
        self.wait_calls = 0
        self.kill_calls = 0

    def wait(self, timeout: float | None = None) -> int:
        self.wait_calls += 1
        if self.wait_calls == 1:
            raise subprocess.TimeoutExpired(cmd="target", timeout=timeout)
        self.returncode = -9
        return self.returncode

    def poll(self) -> int | None:
        return self.returncode

    def kill(self) -> None:
        self.kill_calls += 1


def test_wait_after_termination_retries_with_direct_kill() -> None:
    process = _DelayedReapProcess()

    assert runner_module._wait_after_termination(process) is True  # type: ignore[arg-type]
    assert process.wait_calls == 2
    assert process.kill_calls == 1


def test_real_timeout_includes_bounded_post_termination_reap() -> None:
    started = time.monotonic()
    result = run_process(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        timeout_seconds=0.05,
    )
    elapsed = time.monotonic() - started

    assert elapsed < 3.0
    assert result.timed_out is True
    assert result.infrastructure_error is None
    if os.name == "posix":
        assert result.signal is not None
