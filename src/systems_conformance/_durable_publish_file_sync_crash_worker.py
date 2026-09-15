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

_WORKER_MODULE = "systems_conformance._durable_publish_file_sync_crash_worker"
_PRE_REPLACE_READY = "PRE_REPLACE_READY"


def _spec(operation: str, occurrence: int) -> FaultSpec:
    return FaultSpec(operation=operation, occurrence=occurrence, kind="io_error")


def _publisher(*, file_sync_occurrence: int = 99) -> FaultingDurableFilePublisher:
    return FaultingDurableFilePublisher(
        file_sync_spec=_spec("fsync", file_sync_occurrence),
        replace_spec=_spec("replace", 99),
        directory_sync_spec=_spec("dir_fsync", 99),
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


def _child(staging: pathlib.Path, payload: bytes) -> int:
    _write_synced(staging, payload)
    print(_PRE_REPLACE_READY, flush=True)
    while True:
        time.sleep(60.0)


def _force_kill_before_replace(destination: pathlib.Path, staging: pathlib.Path, payload: bytes) -> None:
    process = subprocess.Popen(
        [sys.executable, "-m", _WORKER_MODULE, "--pre-replace-writer", str(destination), str(staging), payload.hex()],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        if process.stdout is None:
            raise RuntimeError("writer stdout pipe unavailable")
        marker = process.stdout.readline().strip()
        if marker != _PRE_REPLACE_READY:
            stderr = "" if process.stderr is None else process.stderr.read().strip()
            raise RuntimeError(f"writer failed before crash checkpoint: marker={marker!r} stderr={stderr!r}")
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

    initial = b"generation-0\n"
    crashed = b"generation-1\n"
    faulted = b"generation-2\n"
    recovered = b"generation-3\n"

    with tempfile.TemporaryDirectory(prefix="systems-conformance-file-sync-crash-") as directory:
        root = pathlib.Path(directory)
        destination = root / "published.bin"
        crash_staging = root / "crash.tmp"
        fault_staging = root / "fault.tmp"
        recovered_staging = root / "recovered.tmp"

        _write_synced(destination, initial)
        _sync_directory(root)

        _force_kill_before_replace(destination, crash_staging, crashed)
        value_after_crash = destination.read_bytes()
        crashed_staging_value = crash_staging.read_bytes()
        if value_after_crash != initial:
            raise RuntimeError("pre-replace crash changed published destination")
        if crashed_staging_value != crashed:
            raise RuntimeError("pre-replace crash lost synchronized staging payload")

        injected_errno = None
        try:
            _publisher(file_sync_occurrence=0).publish(fault_staging, destination, faulted)
        except OSError as exc:
            injected_errno = exc.errno
        if injected_errno != errno.EIO:
            raise RuntimeError("file sync fault did not inject EIO")
        if destination.read_bytes() != initial:
            raise RuntimeError("file sync failure changed published destination")
        if not fault_staging.exists():
            raise RuntimeError("file sync failure unexpectedly removed staging file")

        _publisher().publish(recovered_staging, destination, recovered)
        if destination.read_bytes() != recovered or recovered_staging.exists():
            raise RuntimeError("publisher did not recover after pre-replace failures")

        payload = {
            "supported": True,
            "initial_value": initial.decode().strip(),
            "pre_replace_writer_forced_crash": True,
            "value_after_pre_replace_crash": value_after_crash.decode().strip(),
            "crashed_staging_preserved": crash_staging.exists(),
            "crashed_staging_value": crashed_staging_value.decode().strip(),
            "injected_file_sync_errno": "EIO",
            "file_sync_failure_destination_unchanged": True,
            "file_sync_failure_staging_preserved": fault_staging.exists(),
            "recovery_publish_value": recovered.decode().strip(),
            "recovery_staging_absent": not recovered_staging.exists(),
        }
        return (json.dumps(payload, separators=(",", ":")) + "\n").encode()


def main() -> int:
    if len(sys.argv) == 5 and sys.argv[1] == "--pre-replace-writer":
        if os.name == "nt":
            print("target_error: directory fsync unavailable", file=sys.stderr)
            return 1
        try:
            return _child(pathlib.Path(sys.argv[3]), bytes.fromhex(sys.argv[4]))
        except (OSError, RuntimeError, ValueError) as exc:
            print(f"target_error: {exc}", file=sys.stderr)
            return 1

    if len(sys.argv) != 1:
        print("protocol_error: unexpected arguments", file=sys.stderr)
        return 2
    if sys.stdin.buffer.read(1):
        print("protocol_error: durable publish file-sync crash target requires empty input", file=sys.stderr)
        return 2

    try:
        sys.stdout.buffer.write(_run())
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"target_error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
