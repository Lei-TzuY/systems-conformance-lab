from __future__ import annotations

import json
import pathlib
import sqlite3
import subprocess
import sys
import tempfile
import time

_WORKER_MODULE = "systems_conformance._sqlite_wal_backup_recovery_worker"


def _read_value(connection: sqlite3.Connection) -> int:
    row = connection.execute("SELECT v FROM items").fetchone()
    if row is None:
        raise RuntimeError("items row missing")
    return int(row[0])


def _integrity_ok(connection: sqlite3.Connection) -> bool:
    return connection.execute("PRAGMA integrity_check").fetchall() == [("ok",)]


def _writer(database: str) -> int:
    connection = sqlite3.connect(database, isolation_level=None, timeout=0.0)
    try:
        connection.execute("PRAGMA busy_timeout = 0")
        connection.execute("BEGIN IMMEDIATE")
        connection.execute("UPDATE items SET v = 1")
        connection.commit()
        print("COMMITTED_READY", flush=True)
        while True:
            time.sleep(60.0)
    finally:
        connection.close()


def _backup(source: str, destination: str) -> int:
    source_connection = sqlite3.connect(source, isolation_level=None, timeout=0.0)
    destination_connection = sqlite3.connect(destination, isolation_level=None, timeout=0.0)
    try:
        source_connection.execute("PRAGMA busy_timeout = 0")
        source_connection.backup(destination_connection)
        if _read_value(destination_connection) != 2:
            raise RuntimeError("backup did not preserve recovered value")
        if not _integrity_ok(destination_connection):
            raise RuntimeError("backup integrity_check failed")
        print("BACKUP_OK", flush=True)
    finally:
        destination_connection.close()
        source_connection.close()
    return 0


def _run_backup_child(source: str, destination: str) -> None:
    completed = subprocess.run(
        [sys.executable, "-m", _WORKER_MODULE, "--backup", source, destination],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=3.0,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            "backup worker failed: "
            f"exit={completed.returncode} stderr={completed.stderr.strip()!r}"
        )
    if completed.stderr.strip():
        raise RuntimeError(f"backup worker emitted stderr: {completed.stderr.strip()!r}")
    if completed.stdout.strip() != "BACKUP_OK":
        raise RuntimeError(f"invalid backup worker result: {completed.stdout.strip()!r}")


def _run() -> bytes:
    with tempfile.TemporaryDirectory(
        prefix="systems-conformance-sqlite-wal-backup-recovery-"
    ) as directory:
        root = pathlib.Path(directory)
        database = str(root / "case.sqlite")
        backup = str(root / "backup.sqlite")

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
            if marker != "COMMITTED_READY":
                stderr = ""
                if process.stderr is not None:
                    stderr = process.stderr.read().strip()
                raise RuntimeError(
                    f"writer failed before forced crash: marker={marker!r} stderr={stderr!r}"
                )
            process.kill()
            _, stderr = process.communicate(timeout=2.0)
            if process.returncode == 0:
                raise RuntimeError("writer unexpectedly exited successfully after forced kill")
            if stderr.strip():
                raise RuntimeError(f"writer emitted stderr before forced kill: {stderr.strip()!r}")
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate(timeout=2.0)

        recovered = sqlite3.connect(database, isolation_level=None, timeout=0.0)
        try:
            recovered.execute("PRAGMA busy_timeout = 0")
            recovered_value = _read_value(recovered)
            if recovered_value != 1:
                raise RuntimeError(f"committed crash recovery mismatch: {recovered_value!r}")
            recovered.execute("BEGIN IMMEDIATE")
            recovered.execute("UPDATE items SET v = 2")
            recovered.commit()
            if _read_value(recovered) != 2:
                raise RuntimeError("post-recovery commit mismatch")
            checkpoint = recovered.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
            if checkpoint is None or len(checkpoint) != 3 or int(checkpoint[0]) != 0:
                raise RuntimeError(f"post-recovery checkpoint failed: {checkpoint!r}")
            if not _integrity_ok(recovered):
                raise RuntimeError("source integrity_check failed after recovery")
        finally:
            recovered.close()

        _run_backup_child(database, backup)

        backup_connection = sqlite3.connect(backup, isolation_level=None, timeout=0.0)
        try:
            backup_value = _read_value(backup_connection)
            backup_integrity = "ok" if _integrity_ok(backup_connection) else "failed"
        finally:
            backup_connection.close()
        if backup_value != 2 or backup_integrity != "ok":
            raise RuntimeError(
                f"independent backup verification failed: value={backup_value!r} "
                f"integrity={backup_integrity!r}"
            )

        payload = {
            "journal_mode": "wal",
            "writer_checkpoint": "committed_update_ready",
            "writer_terminated": True,
            "recovered_value": recovered_value,
            "post_recovery_value": 2,
            "checkpoint_busy": False,
            "source_integrity": "ok",
            "backup_process": "child",
            "backup_value": backup_value,
            "backup_integrity": backup_integrity,
            "backup_reopened": True,
        }
        return (json.dumps(payload, separators=(",", ":")) + "\n").encode()


def main() -> int:
    if len(sys.argv) == 3 and sys.argv[1] == "--writer":
        return _writer(sys.argv[2])
    if len(sys.argv) == 4 and sys.argv[1] == "--backup":
        return _backup(sys.argv[2], sys.argv[3])
    if len(sys.argv) != 1:
        print("protocol_error: unexpected arguments", file=sys.stderr)
        return 2
    if sys.stdin.buffer.read(1):
        print(
            "protocol_error: SQLite WAL backup recovery target requires empty input",
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
