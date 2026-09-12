from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

import systems_conformance.runner as runner_module
from systems_conformance._windows_job import WindowsJob


@pytest.mark.skipif(os.name != "nt", reason="Windows Job Object contract")
def test_windows_job_tracks_and_terminates_real_process() -> None:
    process = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
    )
    job: WindowsJob | None = None
    try:
        job = WindowsJob.create_for_pid(process.pid)
        assert job.active_processes() == 1
        job.terminate()
        process.wait(timeout=2)
        assert process.returncode is not None
        assert job.active_processes() == 0
    finally:
        if job is not None:
            job.close()
        if process.poll() is None:
            process.kill()
            process.wait(timeout=2)


@pytest.mark.skipif(os.name != "nt", reason="Windows Job Object descendant containment")
def test_run_process_detects_redirected_stdio_descendant_after_root_exit(
    tmp_path: Path,
) -> None:
    marker = tmp_path / "escaped.txt"
    child_code = (
        "import pathlib,sys,time; "
        "time.sleep(1.0); "
        "pathlib.Path(sys.argv[1]).write_text('escaped', encoding='utf-8')"
    )
    parent_code = (
        "import subprocess,sys; "
        f"child={child_code!r}; "
        "subprocess.Popen([sys.executable, '-c', child, sys.argv[1]], "
        "stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, "
        "stderr=subprocess.DEVNULL, close_fds=True)"
    )

    result = runner_module.run_process(
        [sys.executable, "-c", parent_code, str(marker)],
        timeout_seconds=3.0,
    )

    assert result.timed_out is False
    assert result.exit_code == 0
    assert result.infrastructure_error == (
        "ProcessTreeLeak: descendant remained alive after root exit"
    )
    time.sleep(1.2)
    assert not marker.exists()


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
