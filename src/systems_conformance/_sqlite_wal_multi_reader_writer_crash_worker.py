from __future__ import annotations

import json
import pathlib
import sqlite3
import subprocess
import sys
import tempfile
import time

from ._sqlite_wal_multi_reader_crash_worker import _checkpoint_is_busy, _commit_value
from ._sqlite_wal_reader_crash_worker import (
    _kill_reader,
    _read_snapshot,
    _read_value,
    _start_reader,
)

_WORKER_MODULE = "systems_conformance._sqlite_wal_multi_reader_writer_crash_worker"


def _writer(database: str, value: int) -> int:
    connection = sqlite3.connect(database, isolation_level=None, timeout=0.0)
    try:
        connection.execute("PRAGMA busy_timeout = 0")
        connection.execute("PRAGMA wal_autocheckpoint = 0")
        connection.execute("BEGIN IMMEDIATE")
        connection.execute("UPDATE items SET v = ?", (value,))
        print("UNCOMMITTED_READY", flush=True)
        while True:
            time.sleep(60.0)
    finally:
        connection.close()


def _start_writer(database: str, value: int) -> subprocess.Popen[str]:
    process = subprocess.Popen(
        [sys.executable, "-m", _WORKER_MODULE, "--writer", database, str(value)],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if process.stdout is None:
        process.kill()
        process.communicate(timeout=2.0)
        raise RuntimeError("writer stdout pipe unavailable")
    marker = process.stdout.readline().strip()
    if marker != "UNCOMMITTED_READY":
        stderr = ""
        if process.stderr is not None:
            stderr = process.stderr.read().strip()
        process.kill()
        process.communicate(timeout=2.0)
        raise RuntimeError(
            "writer failed before crash checkpoint: "
            f"marker={marker!r} stderr={stderr!r}"
        )
    return process


def _kill_writer(process: subprocess.Popen[str]) -> None:
    process.kill()
    _, stderr = process.communicate(timeout=2.0)
    if process.returncode == 0:
        raise RuntimeError("writer unexpectedly exited successfully after forced kill")
    if stderr.strip():
        raise RuntimeError(
            f"writer emitted stderr before forced kill: {stderr.strip()!r}"
        )


def _run() -> bytes:
    with tempfile.TemporaryDirectory(
        prefix="systems-conformance-wal-multi-reader-writer-crash-"
    ) as directory:
        database = str(pathlib.Path(directory) / "target.sqlite")
        connection = sqlite3.connect(database, isolation_level=None)
        try:
            connection.execute("CREATE TABLE items(v INTEGER NOT NULL)")
            connection.execute("INSERT INTO items VALUES (30)")
            journal_mode = str(
                connection.execute("PRAGMA journal_mode = WAL").fetchone()[0]
            ).lower()
            if journal_mode != "wal":
                raise RuntimeError(f"WAL unavailable: {journal_mode!r}")
            connection.execute("PRAGMA wal_autocheckpoint = 0")
        finally:
            connection.close()

        older_reader = _start_reader(database, 30)
        newer_reader: subprocess.Popen[str] | None = None
        writer: subprocess.Popen[str] | None = None
        try:
            first_commit = _commit_value(database, 31)
            _read_snapshot(older_reader, 30)

            newer_reader = _start_reader(database, 31)
            second_commit = _commit_value(database, 32)
            _read_snapshot(newer_reader, 31)

            checkpoint_busy_before_writer = _checkpoint_is_busy(database)
            if not checkpoint_busy_before_writer:
                raise RuntimeError(
                    "truncating checkpoint unexpectedly completed with two pinned readers"
                )

            writer = _start_writer(database, 33)
            _read_snapshot(older_reader, 30)
            _read_snapshot(newer_reader, 31)
            _kill_writer(writer)
            writer = None

            _read_snapshot(older_reader, 30)
            _read_snapshot(newer_reader, 31)
            checkpoint_busy_after_writer_crash = _checkpoint_is_busy(database)
            if not checkpoint_busy_after_writer_crash:
                raise RuntimeError(
                    "writer crash incorrectly released pinned reader checkpoint state"
                )

            _kill_reader(newer_reader)
            checkpoint_busy_after_newer_reader_crash = _checkpoint_is_busy(database)
            if not checkpoint_busy_after_newer_reader_crash:
                raise RuntimeError(
                    "newer reader crash incorrectly released older reader checkpoint state"
                )

            _read_snapshot(older_reader, 30)
            _kill_reader(older_reader)
            checkpoint_busy_after_final_reader_crash = _checkpoint_is_busy(database)
            if checkpoint_busy_after_final_reader_crash:
                raise RuntimeError(
                    "truncating checkpoint remained busy after final reader crash"
                )
        finally:
            if writer is not None and writer.poll() is None:
                writer.kill()
                writer.communicate(timeout=2.0)
            if newer_reader is not None and newer_reader.poll() is None:
                newer_reader.kill()
                newer_reader.communicate(timeout=2.0)
            if older_reader.poll() is None:
                older_reader.kill()
                older_reader.communicate(timeout=2.0)

        post_crash_write = _commit_value(database, 34)

        verified = sqlite3.connect(database, isolation_level=None, timeout=0.0)
        try:
            verified.execute("PRAGMA busy_timeout = 0")
            durable_value = _read_value(verified)
            integrity = verified.execute("PRAGMA integrity_check").fetchall() == [("ok",)]
            final_checkpoint_busy = _checkpoint_is_busy(database)
        finally:
            verified.close()

        if (
            first_commit != 31
            or second_commit != 32
            or post_crash_write != 34
            or durable_value != 34
            or not integrity
            or final_checkpoint_busy
        ):
            raise RuntimeError(
                "multi-reader writer-crash recovery mismatch: "
                f"first_commit={first_commit!r} second_commit={second_commit!r} "
                f"post_crash_write={post_crash_write!r} durable={durable_value!r} "
                f"integrity={integrity!r} final_checkpoint_busy={final_checkpoint_busy!r}"
            )

        payload = {
            "journal_mode": journal_mode,
            "older_reader_snapshot": 30,
            "first_writer_committed_value": first_commit,
            "newer_reader_snapshot": 31,
            "second_writer_committed_value": second_commit,
            "checkpoint_busy_before_writer_crash": checkpoint_busy_before_writer,
            "uncommitted_writer_pending_value": 33,
            "writer_forced_crash": True,
            "older_reader_snapshot_after_writer_crash": 30,
            "newer_reader_snapshot_after_writer_crash": 31,
            "checkpoint_busy_after_writer_crash": checkpoint_busy_after_writer_crash,
            "newer_reader_forced_crash": True,
            "checkpoint_busy_after_newer_reader_crash": (
                checkpoint_busy_after_newer_reader_crash
            ),
            "older_reader_forced_crash": True,
            "checkpoint_busy_after_final_reader_crash": (
                checkpoint_busy_after_final_reader_crash
            ),
            "post_crash_write_value": post_crash_write,
            "fresh_reopen_value": durable_value,
            "fresh_reopen_integrity": "ok",
            "fresh_reopen_checkpoint_busy": final_checkpoint_busy,
        }
        return (json.dumps(payload, separators=(",", ":")) + "\n").encode()


def main() -> int:
    if len(sys.argv) == 4 and sys.argv[1] == "--writer":
        try:
            value = int(sys.argv[3])
        except ValueError:
            print("protocol_error: invalid writer value", file=sys.stderr)
            return 2
        try:
            return _writer(sys.argv[2], value)
        except sqlite3.Error as exc:
            print(f"target_error: {exc}", file=sys.stderr)
            return 1

    if len(sys.argv) != 1:
        print("protocol_error: unexpected arguments", file=sys.stderr)
        return 2
    if sys.stdin.buffer.read(1):
        print(
            "protocol_error: WAL multi-reader writer-crash target requires empty input",
            file=sys.stderr,
        )
        return 2
    try:
        sys.stdout.buffer.write(_run())
    except (OSError, RuntimeError, sqlite3.Error, subprocess.SubprocessError) as exc:
        print(f"target_error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
