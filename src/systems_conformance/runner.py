from __future__ import annotations

import math
import os
import signal
import subprocess
import threading
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import BinaryIO

from ._windows_job import WindowsJob, WindowsJobError
from .model import ExecutionResult, StreamCapture

DEFAULT_MAX_INPUT_BYTES = 16 * 1024 * 1024
DEFAULT_MAX_OUTPUT_BYTES = 1024 * 1024
DEFAULT_MAX_TOTAL_OUTPUT_BYTES = 16 * 1024 * 1024
_READ_CHUNK_BYTES = 64 * 1024
_POST_EXIT_DRAIN_SECONDS = 0.1
_POST_CLEANUP_JOIN_SECONDS = 0.5
_POST_TERMINATION_WAIT_SECONDS = 1.0
_WINDOWS_TREE_KILL_SECONDS = 1.0


class _OutputBudget:
    def __init__(self, max_total_bytes: int) -> None:
        self.max_total_bytes = max_total_bytes
        self.total_bytes = 0
        self.exceeded = threading.Event()
        self._lock = threading.Lock()

    def account(self, size: int) -> None:
        with self._lock:
            self.total_bytes += size
            if self.total_bytes > self.max_total_bytes:
                self.exceeded.set()


class _StreamAccumulator:
    def __init__(self, max_capture_bytes: int, budget: _OutputBudget) -> None:
        self.max_capture_bytes = max_capture_bytes
        self.budget = budget
        self.total_bytes = 0
        self._captured = bytearray()

    def feed(self, chunk: bytes) -> None:
        self.total_bytes += len(chunk)
        self.budget.account(len(chunk))
        remaining = self.max_capture_bytes - len(self._captured)
        if remaining > 0:
            self._captured.extend(chunk[:remaining])

    def snapshot(self) -> StreamCapture:
        return StreamCapture(
            text=bytes(self._captured).decode("utf-8", errors="replace"),
            total_bytes=self.total_bytes,
            truncated=self.total_bytes > self.max_capture_bytes,
        )


def _drain_stream(stream: BinaryIO, accumulator: _StreamAccumulator) -> None:
    try:
        while chunk := os.read(stream.fileno(), _READ_CHUNK_BYTES):
            accumulator.feed(chunk)
    except (OSError, ValueError):
        return


def _write_stdin(stream: BinaryIO, data: bytes) -> None:
    try:
        stream.write(data)
        stream.flush()
    except (BrokenPipeError, OSError, ValueError):
        pass
    finally:
        try:
            stream.close()
        except OSError:
            pass


def _terminate_process_tree(
    process: subprocess.Popen[bytes],
    *,
    root_may_have_exited: bool = False,
    windows_job: WindowsJob | None = None,
) -> None:
    if process.poll() is not None and not root_may_have_exited:
        return

    if os.name == "posix":
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        return

    if os.name == "nt":
        if windows_job is not None:
            try:
                windows_job.terminate()
                return
            except WindowsJobError:
                pass
        try:
            completed = subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
                shell=False,
                timeout=_WINDOWS_TREE_KILL_SECONDS,
            )
        except (OSError, subprocess.TimeoutExpired):
            completed = None
        if (completed is None or completed.returncode != 0) and process.poll() is None:
            try:
                process.kill()
            except OSError:
                pass
        return

    if process.poll() is None:
        process.kill()


def _wait_after_termination(process: subprocess.Popen[bytes]) -> bool:
    """Bound process reaping after the runner has requested termination."""
    try:
        process.wait(timeout=_POST_TERMINATION_WAIT_SECONDS)
        return True
    except subprocess.TimeoutExpired:
        pass

    if process.poll() is None:
        try:
            process.kill()
        except OSError:
            pass

    try:
        process.wait(timeout=_POST_TERMINATION_WAIT_SECONDS)
    except subprocess.TimeoutExpired:
        return False
    return True


def _posix_process_group_survives_root(process: subprocess.Popen[bytes]) -> bool:
    if os.name != "posix":
        return False
    try:
        os.killpg(process.pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _join_io_threads(threads: Sequence[threading.Thread], timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    for thread in threads:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        thread.join(remaining)
    return all(not thread.is_alive() for thread in threads)


def _validate_timeout_seconds(timeout_seconds: float) -> None:
    if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, (int, float)):
        raise TypeError("timeout_seconds must be a finite positive number")
    if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be finite and positive")


def _validate_byte_limit(name: str, value: int, *, allow_zero: bool) -> None:
    qualifier = "non-negative" if allow_zero else "positive"
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be a {qualifier} integer")
    if value < 0 or (not allow_zero and value == 0):
        raise ValueError(f"{name} must be a {qualifier} integer")


def _validate_process_configuration(
    argv: Sequence[str], env: Mapping[str, str] | None
) -> tuple[tuple[str, ...], dict[str, str] | None]:
    if isinstance(argv, (str, bytes)):
        raise TypeError("argv must be a sequence of strings")
    normalized_argv = tuple(argv)
    if not normalized_argv:
        raise ValueError("argv must contain at least one element")
    if any(not isinstance(arg, str) for arg in normalized_argv):
        raise TypeError("argv must be a sequence of strings")

    if env is None:
        return normalized_argv, None
    env_items = tuple(env.items())
    if any(
        not isinstance(key, str) or not isinstance(value, str)
        for key, value in env_items
    ):
        raise TypeError("env keys and values must be strings")
    return normalized_argv, dict(env_items)


def run_process(
    argv: Sequence[str],
    *,
    stdin: bytes = b"",
    cwd: str | os.PathLike[str] | None = None,
    env: Mapping[str, str] | None = None,
    timeout_seconds: float = 10.0,
    max_input_bytes: int = DEFAULT_MAX_INPUT_BYTES,
    max_output_bytes: int = DEFAULT_MAX_OUTPUT_BYTES,
    max_total_output_bytes: int = DEFAULT_MAX_TOTAL_OUTPUT_BYTES,
) -> ExecutionResult:
    """Run one untrusted target without a command shell and return a structured record.

    Input is rejected before process launch when it exceeds ``max_input_bytes``. Stdout and
    stderr are drained concurrently so a target cannot deadlock by filling a pipe. Only
    ``max_output_bytes`` from each stream are retained in memory. A separate aggregate
    ``max_total_output_bytes`` budget bounds how much output the untrusted process may emit at
    all; exceeding it terminates the process tree and is classified as an infrastructure error.
    Descendants that remain in the POSIX target process group after the root exits are killed
    even if they detached from inherited stdio. Windows targets are assigned to a kill-on-close
    Job Object so redirected-stdio descendants are detected and terminated after the root exits.
    Descendants that keep inherited stdio open are also bounded on every supported platform.
    OS- and runtime-level spawn failures, including invalid argv/environment encodings, are
    returned as structured infrastructure errors instead of escaping the execution pipeline.
    Timeout and byte ceilings are validated before process launch; booleans are never accepted
    as numeric execution limits. Argv elements and explicit environment keys/values must already
    be strings so execution configuration is never silently coerced before launch. Caller-owned
    argv/env containers are consumed exactly once into local snapshots before validation so a
    changing container cannot make validation cover different data from process execution. Stdin
    must already be bytes so an invalid payload cannot launch a target and fail later in the
    writer thread after the execution has already started. Once timeout or output cleanup begins,
    root-process reaping is also bounded; a root that remains unreapable after a second direct
    kill attempt is reported as an infrastructure failure instead of blocking indefinitely.
    """
    normalized_argv, process_env = _validate_process_configuration(argv, env)
    _validate_timeout_seconds(timeout_seconds)
    _validate_byte_limit("max_input_bytes", max_input_bytes, allow_zero=True)
    if not isinstance(stdin, bytes):
        raise TypeError("stdin must be bytes")
    if len(stdin) > max_input_bytes:
        raise ValueError(f"stdin exceeds max_input_bytes ({len(stdin)} > {max_input_bytes})")
    _validate_byte_limit("max_output_bytes", max_output_bytes, allow_zero=True)
    _validate_byte_limit("max_total_output_bytes", max_total_output_bytes, allow_zero=False)

    normalized_cwd = str(Path(cwd)) if cwd is not None else None

    popen_kwargs: dict[str, object] = {}
    if os.name == "posix":
        popen_kwargs["start_new_session"] = True
    elif os.name == "nt":
        popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP

    started = time.monotonic()
    timed_out = False
    termination_requested = False
    infrastructure_error: str | None = None
    windows_job: WindowsJob | None = None

    try:
        process = subprocess.Popen(
            normalized_argv,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=normalized_cwd,
            env=process_env,
            shell=False,
            **popen_kwargs,
        )
    except (OSError, ValueError) as exc:
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

    if os.name == "nt":
        try:
            windows_job = WindowsJob.create_for_pid(process.pid)
        except WindowsJobError as exc:
            infrastructure_error = f"WindowsJobError: {exc}"
            termination_requested = True
            _terminate_process_tree(process)

    assert process.stdin is not None
    assert process.stdout is not None
    assert process.stderr is not None

    budget = _OutputBudget(max_total_output_bytes)
    stdout_accumulator = _StreamAccumulator(max_output_bytes, budget)
    stderr_accumulator = _StreamAccumulator(max_output_bytes, budget)

    stdout_thread = threading.Thread(
        target=_drain_stream,
        args=(process.stdout, stdout_accumulator),
        daemon=True,
    )
    stderr_thread = threading.Thread(
        target=_drain_stream,
        args=(process.stderr, stderr_accumulator),
        daemon=True,
    )
    stdin_thread = threading.Thread(
        target=_write_stdin,
        args=(process.stdin, stdin),
        daemon=True,
    )
    io_threads = (stdout_thread, stderr_thread, stdin_thread)
    stdout_thread.start()
    stderr_thread.start()
    stdin_thread.start()

    try:
        deadline = started + timeout_seconds
        while process.poll() is None:
            if budget.exceeded.is_set():
                infrastructure_error = (
                    "OutputLimitExceeded: combined stdout/stderr exceeded "
                    f"{max_total_output_bytes} bytes"
                )
                termination_requested = True
                _terminate_process_tree(process, windows_job=windows_job)
                break
            if time.monotonic() >= deadline:
                timed_out = True
                termination_requested = True
                _terminate_process_tree(process, windows_job=windows_job)
                break
            time.sleep(0.005)

        if termination_requested:
            if not _wait_after_termination(process):
                infrastructure_error = (
                    "ProcessTerminationTimeout: root process remained alive after cleanup"
                )
        else:
            process.wait()

        if _posix_process_group_survives_root(process):
            if infrastructure_error is None and not timed_out:
                infrastructure_error = "ProcessTreeLeak: descendant remained alive after root exit"
            _terminate_process_tree(process, root_may_have_exited=True)

        if os.name == "nt" and windows_job is not None:
            try:
                job_processes = windows_job.active_processes()
            except WindowsJobError as exc:
                if infrastructure_error is None and not timed_out:
                    infrastructure_error = f"WindowsJobError: {exc}"
                job_processes = 1
            if job_processes:
                if infrastructure_error is None and not timed_out:
                    infrastructure_error = (
                        "ProcessTreeLeak: descendant remained alive after root exit"
                    )
                _terminate_process_tree(
                    process,
                    root_may_have_exited=True,
                    windows_job=windows_job,
                )

        if not _join_io_threads(io_threads, _POST_EXIT_DRAIN_SECONDS):
            if infrastructure_error is None and not timed_out:
                infrastructure_error = (
                    "ProcessTreeLeak: descendant kept inherited stdio open after root exit"
                )
            _terminate_process_tree(
                process,
                root_may_have_exited=True,
                windows_job=windows_job,
            )
            _join_io_threads(io_threads, _POST_CLEANUP_JOIN_SECONDS)

        if infrastructure_error is None and budget.exceeded.is_set():
            infrastructure_error = (
                "OutputLimitExceeded: combined stdout/stderr exceeded "
                f"{max_total_output_bytes} bytes"
            )

        return_code = process.returncode
        stdout_capture = stdout_accumulator.snapshot()
        stderr_capture = stderr_accumulator.snapshot()
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
    finally:
        if windows_job is not None:
            windows_job.close()
