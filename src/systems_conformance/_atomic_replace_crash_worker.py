from __future__ import annotations

import errno
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import time

from .fault import FaultSpec
from .replace_fault import FaultingAtomicReplace

_WORKER_MODULE = "systems_conformance._atomic_replace_crash_worker"
_PRE_READY = "PRE_REPLACE_READY"
_POST_READY = "POST_REPLACE_READY"


def _write_synced(path: pathlib.Path, payload: bytes) -> None:
    with path.open("wb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())


def _child(mode: str, destination: pathlib.Path, staging: pathlib.Path, payload: bytes) -> int:
    _write_synced(staging, payload)
    if mode == "--pre-replace-writer":
        print(_PRE_READY, flush=True)
    elif mode == "--post-replace-writer":
        os.replace(staging, destination)
        print(_POST_READY, flush=True)
    else:
        raise ValueError(f"unsupported child mode: {mode}")

    while True:
        time.sleep(60.0)


def _force_kill_after_marker(
    mode: str,
    destination: pathlib.Path,
    staging: pathlib.Path,
    payload: bytes,
    expected_marker: str,
) -> None:
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            _WORKER_MODULE,
            mode,
            str(destination),
            str(staging),
            payload.hex(),
        ],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        if process.stdout is None:
            raise RuntimeError("writer stdout pipe unavailable")
        marker = process.stdout.readline().strip()
        if marker != expected_marker:
            stderr = "" if process.stderr is None else process.stderr.read().strip()
            raise RuntimeError(
                f"writer failed before crash checkpoint: marker={marker!r} stderr={stderr!r}"
            )
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


def _read_exact(path: pathlib.Path) -> bytes:
    return path.read_bytes()


def _run() -> bytes:
    generations = {
        "initial": b"generation-0\n",
        "pre_crash": b"generation-1\n",
        "post_crash": b"generation-2\n",
        "faulted": b"generation-3\n",
        "followup": b"generation-4\n",
    }

    with tempfile.TemporaryDirectory(prefix="systems-conformance-atomic-replace-crash-") as directory:
        root = pathlib.Path(directory)
        destination = root / "published.bin"
        pre_staging = root / "pre.bin.tmp"
        post_staging = root / "post.bin.tmp"
        fault_staging = root / "fault.bin.tmp"
        followup_staging = root / "followup.bin.tmp"

        _write_synced(destination, generations["initial"])
        initial_value = _read_exact(destination)
        if initial_value != generations["initial"]:
            raise RuntimeError("initial destination contents mismatch")

        _force_kill_after_marker(
            "--pre-replace-writer",
            destination,
            pre_staging,
            generations["pre_crash"],
            _PRE_READY,
        )
        value_after_pre_crash = _read_exact(destination)
        pre_staging_exists = pre_staging.exists()
        if value_after_pre_crash != generations["initial"] or not pre_staging_exists:
            raise RuntimeError("pre-publication crash boundary mismatch")
        pre_staging.unlink()

        _force_kill_after_marker(
            "--post-replace-writer",
            destination,
            post_staging,
            generations["post_crash"],
            _POST_READY,
        )
        value_after_post_crash = _read_exact(destination)
        post_staging_absent = not post_staging.exists()
        if value_after_post_crash != generations["post_crash"] or not post_staging_absent:
            raise RuntimeError("post-publication crash boundary mismatch")

        _write_synced(fault_staging, generations["faulted"])
        faulting_replace = FaultingAtomicReplace(
            FaultSpec(operation="replace", occurrence=0, kind="io_error")
        )
        injected_errno = None
        try:
            faulting_replace.replace(fault_staging, destination)
        except OSError as exc:
            injected_errno = exc.errno
        if injected_errno != errno.EIO or not faulting_replace.triggered:
            raise RuntimeError("deterministic replace fault did not inject EIO")
        value_after_fault = _read_exact(destination)
        fault_staging_preserved = fault_staging.exists()
        if value_after_fault != generations["post_crash"] or not fault_staging_preserved:
            raise RuntimeError("failed replace mutated published destination or staging file")
        fault_staging.unlink()

        _write_synced(followup_staging, generations["followup"])
        os.replace(followup_staging, destination)
        followup_value = _read_exact(destination)
        followup_staging_absent = not followup_staging.exists()
        if followup_value != generations["followup"] or not followup_staging_absent:
            raise RuntimeError("follow-up atomic replace failed")

        payload = {
            "initial_value": initial_value.decode().strip(),
            "pre_publish_staging_synced": True,
            "pre_publish_writer_forced_crash": True,
            "value_after_pre_publish_crash": value_after_pre_crash.decode().strip(),
            "pre_publish_staging_survived": pre_staging_exists,
            "post_publish_staging_synced": True,
            "post_publish_replace_completed": True,
            "post_publish_writer_forced_crash": True,
            "value_after_post_publish_crash": value_after_post_crash.decode().strip(),
            "post_publish_staging_absent": post_staging_absent,
            "injected_replace_errno": "EIO",
            "value_after_injected_replace_failure": value_after_fault.decode().strip(),
            "fault_staging_preserved": fault_staging_preserved,
            "followup_value": followup_value.decode().strip(),
            "followup_staging_absent": followup_staging_absent,
        }
        return (json.dumps(payload, separators=(",", ":")) + "\n").encode()


def main() -> int:
    if len(sys.argv) == 6 and sys.argv[1] in {"--pre-replace-writer", "--post-replace-writer"}:
        try:
            return _child(
                sys.argv[1],
                pathlib.Path(sys.argv[2]),
                pathlib.Path(sys.argv[3]),
                bytes.fromhex(sys.argv[4]),
            )
        except (OSError, RuntimeError, ValueError) as exc:
            print(f"target_error: {exc}", file=sys.stderr)
            return 1

    if len(sys.argv) != 1:
        print("protocol_error: unexpected arguments", file=sys.stderr)
        return 2
    if sys.stdin.buffer.read(1):
        print("protocol_error: atomic replace crash target requires empty input", file=sys.stderr)
        return 2

    try:
        sys.stdout.buffer.write(_run())
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"target_error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
