from __future__ import annotations

import os
import sys

import pytest

import systems_conformance.runner as runner_module


@pytest.mark.skipif(os.name != "nt", reason="Windows taskkill fallback contract")
def test_taskkill_timeout_falls_back_to_direct_root_kill(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    process = runner_module.subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        creationflags=runner_module.subprocess.CREATE_NEW_PROCESS_GROUP,
    )

    def timeout_taskkill(*args: object, **kwargs: object) -> object:
        raise runner_module.subprocess.TimeoutExpired(cmd="taskkill", timeout=1.0)

    monkeypatch.setattr(runner_module.subprocess, "run", timeout_taskkill)
    try:
        runner_module._terminate_process_tree(process)
        process.wait(timeout=2)
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=2)

    assert process.returncode is not None
