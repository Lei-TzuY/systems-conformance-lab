from __future__ import annotations

import os
import signal
import subprocess
import tempfile
import time
from collections.abc import Mapping, Sequence
from pathlib import Path

from .model import ExecutionResult, StreamCapture

DEFAULT_MAX_OUTPUT_BYTES = 1024 * 1024


def _capture_stream(file_obj, max_bytes: int) -> StreamCapture:
    file_obj.flush()
    file_obj.seek(0, os.SEEK_END)
    total_bytes = file_obj.tell()
    file_obj.seek(0)
    data = file_obj.read(max_bytes)
    return StreamCapture(
        text=data.decode("utf-8", errors="replace"),
        total_bytes=total_bytes,
        truncated=total_bytes > max_bytes,
    )


def _terminate_process_tree(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return

    if os.name == "posix":
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        return

    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            shell=False,
        )
        return

    process.kill()


def run_process(
    argv: Sequence[str],
    *,
    stdin: bytes = b"",
    cwd: str | os.PathLike[str] | None = None,
    env: Mapping[str, str] | None = None,
    timeout_seconds: float = 10.0,
    max_output_bytes: int = DEFAULT_MAX_OUTPUT_BYTES,
) -> ExecutionResult:
    """Run one untrusted target without a command shell and return a structured record.

    Output is redirected to temporary files rather than pipes so a target cannot deadlock by
    filling an unread pipe. Only ``max_output_bytes`` from each stream are retained in memory,
    while ``total_bytes`` records the complete stream size.
    """
    if not argv:
        raise ValueError("argv must contain at least one element")
    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be positive")
    if max_output_bytes < 0:
        raise ValueError("max_output_bytes must be non-negative")

    normalized_argv = tuple(str(arg) for arg in argv)
    normalized_cwd = str(Path(cwd)) if cwd is not None else None
    process_env = None if env is None else {str(key): str(value) for key, value in env.items()}

    popen_kwargs: dict[str, object] = {}
    if os.name == "posix":
        popen_kwargs["start_new_session"] = True
    elif os.name == "nt":
        popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP

    started = time.monotonic()
    timed_out = False
    infrastructure_error: str | None = None
    return_code: int | None = None

    with tempfile.TemporaryFile() as stdout_file, tempfile.TemporaryFile() as stderr_file:
        try:
            process = subprocess.Popen(
                normalized_argv,
                stdin=subprocess.PIPE,
                stdout=stdout_file,
                stderr=stderr_file,
                cwd=normalized_cwd,
                env=process_env,
                shell=False,
                **popen_kwargs,
            )
        except OSError as exc:
            duration_ms = round((time.monotonic() - started) * 1000)
            empty = StreamCapture(text="", total_bytes=0, truncated=False)
            return ExecutionResult(
                argv=normalized_argv,
                duration_ms=duration_ms,
                timed_out=False,
                exit_code=None,
                signal=None,
                stdout=empty,
                stderr=empty,
                infrastructure_error=f"{type(exc).__name__}: {exc}",
            )

        try:
            process.communicate(input=stdin, timeout=timeout_seconds)
        except subprocess.TimeoutExpired:
            timed_out = True
            _terminate_process_tree(process)
            process.communicate()
        return_code = process.returncode

        stdout_capture = _capture_stream(stdout_file, max_output_bytes)
        stderr_capture = _capture_stream(stderr_file, max_output_bytes)

    duration_ms = round((time.monotonic() - started) * 1000)
    terminating_signal = -return_code if return_code is not None and return_code < 0 else None
    exit_code = return_code if return_code is not None and return_code >= 0 else None

    return ExecutionResult(
        argv=normalized_argv,
        duration_ms=duration_ms,
        timed_out=timed_out,
        exit_code=exit_code,
        signal=terminating_signal,
        stdout=stdout_capture,
        stderr=stderr_capture,
        infrastructure_error=infrastructure_error,
    )
