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


def _write_value(connection: sqlite3.Connection, value: int) -> None:
    connection.execute("BEGIN IMMEDIATE")
    connection.execute("UPDATE items SET v = ?", (value,))
    connection.commit()


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


def _detached_wal_writer(database: str) -> int:
    connection = sqlite3.connect(database, isolation_level=None, timeout=0.0)
    try:
        connection.execute("PRAGMA busy_timeout = 0")
        row = connection.execute("PRAGMA journal_mode = WAL").fetchone()
        actual = None if row is None else str(row[0]).lower()
        if actual != "wal":
            raise RuntimeError(f"detached backup WAL unavailable: got {actual}")
        connection.execute("PRAGMA wal_autocheckpoint = 0")
        _write_value(connection, 6)
        print("DETACHED_WAL_COMMITTED_READY", flush=True)
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


def _verify_detached_backup(database: str) -> int:
    connection = sqlite3.connect(database, isolation_level=None, timeout=0.0)
    try:
        connection.execute("PRAGMA busy_timeout = 0")
        if _read_value(connection) != 4:
            raise RuntimeError("detached backup did not preserve independent value")
        if not _integrity_ok(connection):
            raise RuntimeError("detached backup integrity_check failed before write")
        _write_value(connection, 5)
        if _read_value(connection) != 5:
            raise RuntimeError("detached backup post-source-deletion write mismatch")
        if not _integrity_ok(connection):
            raise RuntimeError("detached backup integrity_check failed after write")
        print("DETACHED_BACKUP_OK", flush=True)
    finally:
        connection.close()
    return 0


def _run_child(arguments: list[str], expected_stdout: str, label: str) -> None:
    completed = subprocess.run(
        [sys.executable, "-m", _WORKER_MODULE, *arguments],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=3.0,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"{label} worker failed: "
            f"exit={completed.returncode} stderr={completed.stderr.strip()!r}"
        )
    if completed.stderr.strip():
        raise RuntimeError(f"{label} worker emitted stderr: {completed.stderr.strip()!r}")
    if completed.stdout.strip() != expected_stdout:
        raise RuntimeError(
            f"invalid {label} worker result: {completed.stdout.strip()!r}"
        )


def _run_backup_child(source: str, destination: str) -> None:
    _run_child(["--backup", source, destination], "BACKUP_OK", "backup")


def _run_detached_backup_child(database: str) -> None:
    _run_child(
        ["--verify-detached-backup", database],
        "DETACHED_BACKUP_OK",
        "detached backup",
    )


def _force_kill_after_marker(
    arguments: list[str], expected_marker: str, label: str
) -> None:
    process = subprocess.Popen(
        [sys.executable, "-m", _WORKER_MODULE, *arguments],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        if process.stdout is None:
            raise RuntimeError(f"{label} stdout pipe unavailable")
        marker = process.stdout.readline().strip()
        if marker != expected_marker:
            stderr = ""
            if process.stderr is not None:
                stderr = process.stderr.read().strip()
            raise RuntimeError(
                f"{label} failed before forced crash: marker={marker!r} stderr={stderr!r}"
            )
        process.kill()
        _, stderr = process.communicate(timeout=2.0)
        if process.returncode == 0:
            raise RuntimeError(f"{label} unexpectedly exited successfully after forced kill")
        if stderr.strip():
            raise RuntimeError(f"{label} emitted stderr before forced kill: {stderr.strip()!r}")
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate(timeout=2.0)


def _remove_source_database(database: str) -> None:
    for path in (database, f"{database}-wal", f"{database}-shm"):
        try:
            pathlib.Path(path).unlink()
        except FileNotFoundError:
            pass


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

        _force_kill_after_marker(
            ["--writer", database], "COMMITTED_READY", "writer"
        )

        recovered = sqlite3.connect(database, isolation_level=None, timeout=0.0)
        try:
            recovered.execute("PRAGMA busy_timeout = 0")
            recovered_value = _read_value(recovered)
            if recovered_value != 1:
                raise RuntimeError(f"committed crash recovery mismatch: {recovered_value!r}")
            _write_value(recovered, 2)
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

        source_connection = sqlite3.connect(database, isolation_level=None, timeout=0.0)
        backup_connection = sqlite3.connect(backup, isolation_level=None, timeout=0.0)
        try:
            source_connection.execute("PRAGMA busy_timeout = 0")
            backup_connection.execute("PRAGMA busy_timeout = 0")

            _write_value(source_connection, 3)
            source_after_source_write = _read_value(source_connection)
            backup_after_source_write = _read_value(backup_connection)
            if source_after_source_write != 3 or backup_after_source_write != 2:
                raise RuntimeError(
                    "backup changed with source mutation: "
                    f"source={source_after_source_write!r} "
                    f"backup={backup_after_source_write!r}"
                )

            _write_value(backup_connection, 4)
            backup_after_backup_write = _read_value(backup_connection)
            source_after_backup_write = _read_value(source_connection)
            if backup_after_backup_write != 4 or source_after_backup_write != 3:
                raise RuntimeError(
                    "source changed with backup mutation: "
                    f"source={source_after_backup_write!r} "
                    f"backup={backup_after_backup_write!r}"
                )
            if not _integrity_ok(source_connection):
                raise RuntimeError("source integrity_check failed after independence writes")
            if not _integrity_ok(backup_connection):
                raise RuntimeError("backup integrity_check failed after independence writes")
        finally:
            backup_connection.close()
            source_connection.close()

        _remove_source_database(database)
        if pathlib.Path(database).exists():
            raise RuntimeError("source database remained after deletion boundary")

        _run_detached_backup_child(backup)

        detached_backup = sqlite3.connect(backup, isolation_level=None, timeout=0.0)
        try:
            detached_backup_value = _read_value(detached_backup)
            detached_backup_integrity = (
                "ok" if _integrity_ok(detached_backup) else "failed"
            )
        finally:
            detached_backup.close()
        if detached_backup_value != 5 or detached_backup_integrity != "ok":
            raise RuntimeError(
                "detached backup parent verification failed: "
                f"value={detached_backup_value!r} integrity={detached_backup_integrity!r}"
            )

        _force_kill_after_marker(
            ["--detached-wal-writer", backup],
            "DETACHED_WAL_COMMITTED_READY",
            "detached WAL writer",
        )

        detached_wal_recovery = sqlite3.connect(backup, isolation_level=None, timeout=0.0)
        try:
            detached_wal_recovery.execute("PRAGMA busy_timeout = 0")
            row = detached_wal_recovery.execute("PRAGMA journal_mode").fetchone()
            detached_backup_wal_mode = None if row is None else str(row[0]).lower()
            detached_backup_wal_value = _read_value(detached_wal_recovery)
            detached_backup_wal_integrity = (
                "ok" if _integrity_ok(detached_wal_recovery) else "failed"
            )
            checkpoint = detached_wal_recovery.execute(
                "PRAGMA wal_checkpoint(TRUNCATE)"
            ).fetchone()
            detached_backup_wal_checkpoint_busy = not (
                checkpoint is not None
                and len(checkpoint) == 3
                and int(checkpoint[0]) == 0
            )
        finally:
            detached_wal_recovery.close()
        if detached_backup_wal_mode != "wal":
            raise RuntimeError(
                f"detached backup did not retain WAL mode: {detached_backup_wal_mode!r}"
            )
        if detached_backup_wal_value != 6:
            raise RuntimeError(
                f"detached backup second crash recovery mismatch: {detached_backup_wal_value!r}"
            )
        if detached_backup_wal_integrity != "ok":
            raise RuntimeError("detached backup second crash integrity_check failed")
        if detached_backup_wal_checkpoint_busy:
            raise RuntimeError("detached backup second crash checkpoint remained busy")

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
            "source_after_source_write": source_after_source_write,
            "backup_after_source_write": backup_after_source_write,
            "backup_after_backup_write": backup_after_backup_write,
            "source_after_backup_write": source_after_backup_write,
            "independent_writes_integrity": "ok",
            "source_deleted": True,
            "detached_backup_process": "child",
            "detached_backup_value": detached_backup_value,
            "detached_backup_integrity": detached_backup_integrity,
            "detached_backup_reopened": True,
            "detached_backup_wal_mode": detached_backup_wal_mode,
            "detached_backup_wal_writer_terminated": True,
            "detached_backup_wal_value": detached_backup_wal_value,
            "detached_backup_wal_integrity": detached_backup_wal_integrity,
            "detached_backup_wal_checkpoint_busy": detached_backup_wal_checkpoint_busy,
        }
        return (json.dumps(payload, separators=(",", ":")) + "\n").encode()


def main() -> int:
    if len(sys.argv) == 3 and sys.argv[1] == "--writer":
        return _writer(sys.argv[2])
    if len(sys.argv) == 3 and sys.argv[1] == "--detached-wal-writer":
        return _detached_wal_writer(sys.argv[2])
    if len(sys.argv) == 4 and sys.argv[1] == "--backup":
        return _backup(sys.argv[2], sys.argv[3])
    if len(sys.argv) == 3 and sys.argv[1] == "--verify-detached-backup":
        return _verify_detached_backup(sys.argv[2])
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
