from __future__ import annotations

import errno
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import time

from .durable_publish import FaultingDurableFilePublisher
from .fault import FaultSpec

_WORKER_MODULE = "systems_conformance._durable_publish_crash_worker"
_PRE_DIRSYNC_READY = "PRE_DIRSYNC_READY"
_POST_PUBLISH_READY = "POST_PUBLISH_READY"


def _spec(operation: str, occurrence: int) -> FaultSpec:
    return FaultSpec(operation=operation, occurrence=occurrence, kind="io_error")


def _publisher(*, directory_sync_occurrence: int = 99) -> FaultingDurableFilePublisher:
    return FaultingDurableFilePublisher(
        file_sync_spec=_spec("fsync", 99),
        replace_spec=_spec("replace", 99),
        directory_sync_spec=_spec("dir_fsync", directory_sync_occurrence),
    )


def _write_synced(path: pathlib.Path, payload: bytes) -> None:
    with path.open("wb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())


def _sync_directory(directory: pathlib.Path) -> None:
    fd = os.open(directory, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _child(mode: str, destination: pathlib.Path, staging: pathlib.Path, payload: bytes) -> int:
    if mode == "--pre-dirsync-writer":
        _write_synced(staging, payload)
        os.replace(staging, destination)
        print(_PRE_DIRSYNC_READY, flush=True)
    elif mode == "--post-publish-writer":
        _publisher().publish(staging, destination, payload)
        print(_POST_PUBLISH_READY, flush=True)
    else:
        raise ValueError(f"unsupported child mode: {mode}")

    while True:
        time.sleep(60.0)


def _force_kill_after_marker(
    mode: str,
    destination: pathlib.Path,
    staging: pathlib.Path,
    payload: bytes,
    marker: str,
) -> None:
    process = subprocess.Popen(
        [sys.executable, "-m", _WORKER_MODULE, mode, str(destination), str(staging), payload.hex()],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        if process.stdout is None:
            raise RuntimeError("writer stdout pipe unavailable")
        actual = process.stdout.readline().strip()
        if actual != marker:
            stderr = "" if process.stderr is None else process.stderr.read().strip()
            raise RuntimeError(f"writer failed before crash checkpoint: marker={actual!r} stderr={stderr!r}")
        process.kill()
        _, stderr = process.communicate(timeout=2.0)
        if process.returncode == 0:
            raise RuntimeError("writer unexpectedly exited successfully")
        if stderr.strip():
            raise RuntimeError(f"writer emitted stderr: {stderr.strip()!r}")
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate(timeout=2.0)


def _run() -> bytes:
    if os.name == "nt":
        return b'{"supported":false,"reason":"directory fsync unavailable"}\n'

    generations = {
        "initial": b"generation-0\n",
        "pre_dirsync": b"generation-1\n",
        "dirsync_fault": b"generation-2\n",
        "durable": b"generation-3\n",
    }

    with tempfile.TemporaryDirectory(prefix="systems-conformance-durable-publish-crash-") as directory:
        root = pathlib.Path(directory)
        destination = root / "published.bin"
        pre_staging = root / "pre.tmp"
        fault_staging = root / "fault.tmp"
        durable_staging = root / "durable.tmp"

        _write_synced(destination, generations["initial"])
        _sync_directory(root)

        _force_kill_after_marker(
            "--pre-dirsync-writer",
            destination,
            pre_staging,
            generations["pre_dirsync"],
            _PRE_DIRSYNC_READY,
        )
        value_after_pre_dirsync_crash = destination.read_bytes()
        if value_after_pre_dirsync_crash != generations["pre_dirsync"] or pre_staging.exists():
            raise RuntimeError("replace-before-directory-sync crash boundary mismatch")

        injected_errno = None
        try:
            _publisher(directory_sync_occurrence=0).publish(
                fault_staging, destination, generations["dirsync_fault"]
            )
        except OSError as exc:
            injected_errno = exc.errno
        if injected_errno != errno.EIO:
            raise RuntimeError("directory sync fault did not inject EIO")
        value_after_dirsync_fault = destination.read_bytes()
        if value_after_dirsync_fault != generations["dirsync_fault"] or fault_staging.exists():
            raise RuntimeError("directory sync fault changed replace visibility contract")

        _force_kill_after_marker(
            "--post-publish-writer",
            destination,
            durable_staging,
            generations["durable"],
            _POST_PUBLISH_READY,
        )
        value_after_completed_publish_crash = destination.read_bytes()
        if value_after_completed_publish_crash != generations["durable"] or durable_staging.exists():
            raise RuntimeError("completed durable publish crash boundary mismatch")

        payload = {
            "supported": True,
            "initial_value": generations["initial"].decode().strip(),
            "pre_dirsync_replace_completed": True,
            "pre_dirsync_writer_forced_crash": True,
            "value_after_pre_dirsync_crash": value_after_pre_dirsync_crash.decode().strip(),
            "pre_dirsync_staging_absent": not pre_staging.exists(),
            "injected_directory_sync_errno": "EIO",
            "value_after_directory_sync_failure": value_after_dirsync_fault.decode().strip(),
            "directory_sync_failure_staging_absent": not fault_staging.exists(),
            "completed_publish_returned": True,
            "post_publish_writer_forced_crash": True,
            "value_after_completed_publish_crash": value_after_completed_publish_crash.decode().strip(),
            "completed_publish_staging_absent": not durable_staging.exists(),
        }
        return (json.dumps(payload, separators=(",", ":")) + "\n").encode()


def main() -> int:
    if len(sys.argv) == 5 and sys.argv[1] in {"--pre-dirsync-writer", "--post-publish-writer"}:
        if os.name == "nt":
            print("target_error: directory fsync unavailable", file=sys.stderr)
            return 1
        try:
            return _child(sys.argv[1], pathlib.Path(sys.argv[2]), pathlib.Path(sys.argv[3]), bytes.fromhex(sys.argv[4]))
        except (OSError, RuntimeError, ValueError) as exc:
            print(f"target_error: {exc}", file=sys.stderr)
            return 1

    if len(sys.argv) != 1:
        print("protocol_error: unexpected arguments", file=sys.stderr)
        return 2
    if sys.stdin.buffer.read(1):
        print("protocol_error: durable publish crash target requires empty input", file=sys.stderr)
        return 2

    try:
        sys.stdout.buffer.write(_run())
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"target_error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
