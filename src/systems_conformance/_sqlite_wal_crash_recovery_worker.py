from __future__ import annotations

import json
import pathlib
import sqlite3
import subprocess
import sys
import tempfile
import time


_WORKER_MODULE = "systems_conformance._sqlite_wal_crash_recovery_worker"


def _writer(database: str) -> int:
    connection = sqlite3.connect(database, isolation_level=None, timeout=0.0)
    try:
        connection.execute("PRAGMA busy_timeout = 0")
        connection.execute("BEGIN IMMEDIATE")
        connection.execute("UPDATE items SET v = 1")
        print("READY", flush=True)
        while True:
            time.sleep(60.0)
    finally:
        connection.close()


def _run() -> bytes:
    with tempfile.TemporaryDirectory(
        prefix="systems-conformance-sqlite-wal-crash-recovery-"
    ) as directory:
        database = str(pathlib.Path(directory) / "case.sqlite")
        bootstrap = sqlite3.connect(database, isolation_level=None)
        try:
            row = bootstrap.execute("PRAGMA journal_mode = WAL").fetchone()
            actual = None if row is None else str(row[0]).lower()
            if actual != "wal":
                raise RuntimeError(f"SQLite WAL unavailable: got {actual}")
            bootstrap.execute("PRAGMA wal_autocheckpoint = 0")
            bootstrap.execute("CREATE TABLE items(v INTEGER NOT NULL)")
            bootstrap.execute("INSERT INTO items VALUES (0)")
        finally:
            bootstrap.close()

        process = subprocess.Popen(
            [sys.executable, "-m", _WORKER_MODULE, "--writer", database],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            if process.stdout is None:
                raise RuntimeError("writer stdout pipe unavailable")
            marker = process.stdout.readline().strip()
            if marker != "READY":
                stderr = ""
                if process.stderr is not None:
                    stderr = process.stderr.read().strip()
                raise RuntimeError(
                    "writer failed before crash checkpoint: "
                    f"marker={marker!r} stderr={stderr!r}"
                )
            process.kill()
            _, stderr = process.communicate(timeout=2.0)
            if process.returncode == 0:
                raise RuntimeError("writer unexpectedly exited successfully after forced kill")
            if stderr.strip():
                raise RuntimeError(
                    f"writer emitted stderr before forced kill: {stderr.strip()!r}"
                )
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate(timeout=2.0)

        recovered = sqlite3.connect(database, isolation_level=None, timeout=0.0)
        try:
            recovered.execute("PRAGMA busy_timeout = 0")
            row = recovered.execute("SELECT v FROM items").fetchone()
            if row is None or int(row[0]) != 0:
                raise RuntimeError(f"uncommitted writer state survived crash: {row!r}")
            recovered_value = int(row[0])

            recovered.execute("BEGIN IMMEDIATE")
            recovered.execute("UPDATE items SET v = 2")
            recovered.commit()
            row = recovered.execute("SELECT v FROM items").fetchone()
            if row is None or int(row[0]) != 2:
                raise RuntimeError(f"fresh commit after recovery mismatch: {row!r}")
        finally:
            recovered.close()

        payload = {
            "journal_mode": "wal",
            "writer_checkpoint": "uncommitted_update_ready",
            "writer_terminated": True,
            "recovered_value": recovered_value,
            "fresh_committed_value": 2,
        }
        return (json.dumps(payload, separators=(",", ":")) + "\n").encode()


def main() -> int:
    if len(sys.argv) == 3 and sys.argv[1] == "--writer":
        return _writer(sys.argv[2])
    if len(sys.argv) != 1:
        print("protocol_error: unexpected arguments", file=sys.stderr)
        return 2
    if sys.stdin.buffer.read(1):
        print(
            "protocol_error: SQLite WAL crash recovery target requires empty input",
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
