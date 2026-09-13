from __future__ import annotations

import json
import pathlib
import sqlite3
import subprocess
import sys
import tempfile
import time

from ._sqlite_wal_backup_recovery_worker import (
    _integrity_ok,
    _read_value,
    _remove_source_database,
    _write_value,
)

_WORKER_MODULE = "systems_conformance._sqlite_wal_backup_uncommitted_crash_worker"


def _uncommitted_writer(database: str, pending_value: int) -> int:
    connection = sqlite3.connect(database, isolation_level=None, timeout=0.0)
    try:
        connection.execute("PRAGMA busy_timeout = 0")
        row = connection.execute("PRAGMA journal_mode = WAL").fetchone()
        actual = None if row is None else str(row[0]).lower()
        if actual != "wal":
            raise RuntimeError(f"detached backup WAL unavailable: {actual!r}")
        connection.execute("PRAGMA wal_autocheckpoint = 0")
        connection.execute("BEGIN IMMEDIATE")
        connection.execute("UPDATE items SET v = ?", (pending_value,))
        if _read_value(connection) != pending_value:
            raise RuntimeError("uncommitted backup writer could not observe pending mutation")
        print(f"UNCOMMITTED_BACKUP_READY:{pending_value}", flush=True)
        while True:
            time.sleep(60.0)
    finally:
        connection.close()


def _force_kill_uncommitted(database: str, pending_value: int) -> None:
    process = subprocess.Popen(
        [sys.executable, "-m", _WORKER_MODULE, "--uncommitted-writer", database, str(pending_value)],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        if process.stdout is None:
            raise RuntimeError("uncommitted backup writer stdout pipe unavailable")
        marker = process.stdout.readline().strip()
        expected = f"UNCOMMITTED_BACKUP_READY:{pending_value}"
        if marker != expected:
            stderr = "" if process.stderr is None else process.stderr.read().strip()
            raise RuntimeError(
                f"backup writer failed before forced crash: marker={marker!r} stderr={stderr!r}"
            )
        process.kill()
        _, stderr = process.communicate(timeout=2.0)
        if process.returncode == 0:
            raise RuntimeError("uncommitted backup writer unexpectedly exited successfully")
        if stderr.strip():
            raise RuntimeError(f"uncommitted backup writer emitted stderr: {stderr.strip()!r}")
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate(timeout=2.0)


def _checkpoint_busy(database: str) -> bool:
    connection = sqlite3.connect(database, isolation_level=None, timeout=0.0)
    try:
        connection.execute("PRAGMA busy_timeout = 0")
        row = connection.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
    finally:
        connection.close()
    return not (row is not None and len(row) == 3 and int(row[0]) == 0)


def _run() -> bytes:
    with tempfile.TemporaryDirectory(
        prefix="systems-conformance-wal-backup-uncommitted-crash-"
    ) as directory:
        root = pathlib.Path(directory)
        source = str(root / "source.sqlite")
        backup = str(root / "backup.sqlite")

        source_connection = sqlite3.connect(source, isolation_level=None)
        try:
            source_connection.execute("CREATE TABLE items(v INTEGER NOT NULL)")
            source_connection.execute("INSERT INTO items VALUES (200)")
            journal_mode = str(
                source_connection.execute("PRAGMA journal_mode = WAL").fetchone()[0]
            ).lower()
            if journal_mode != "wal":
                raise RuntimeError(f"source WAL unavailable: {journal_mode!r}")
            source_connection.execute("PRAGMA wal_autocheckpoint = 0")
            _write_value(source_connection, 201)
            source_before_backup = _read_value(source_connection)

            backup_connection = sqlite3.connect(backup, isolation_level=None, timeout=0.0)
            try:
                source_connection.backup(backup_connection)
                backup_initial_value = _read_value(backup_connection)
                backup_initial_integrity = _integrity_ok(backup_connection)
            finally:
                backup_connection.close()

            _write_value(source_connection, 202)
            source_after_backup = _read_value(source_connection)
        finally:
            source_connection.close()

        backup_observer = sqlite3.connect(backup, isolation_level=None, timeout=0.0)
        try:
            backup_after_source_commit = _read_value(backup_observer)
        finally:
            backup_observer.close()

        if (
            source_before_backup != 201
            or backup_initial_value != 201
            or not backup_initial_integrity
            or source_after_backup != 202
            or backup_after_source_commit != 201
        ):
            raise RuntimeError("source/backup pre-crash independence mismatch")

        _remove_source_database(source)
        source_deleted = not any(
            pathlib.Path(path).exists() for path in (source, f"{source}-wal", f"{source}-shm")
        )
        if not source_deleted:
            raise RuntimeError("source files remained after deletion boundary")

        _force_kill_uncommitted(backup, 203)

        recovered = sqlite3.connect(backup, isolation_level=None, timeout=0.0)
        try:
            recovered.execute("PRAGMA busy_timeout = 0")
            row = recovered.execute("PRAGMA journal_mode").fetchone()
            backup_wal_mode = None if row is None else str(row[0]).lower()
            backup_value_after_crash = _read_value(recovered)
            backup_integrity_after_crash = _integrity_ok(recovered)
        finally:
            recovered.close()

        checkpoint_busy_after_crash = _checkpoint_busy(backup)
        if backup_wal_mode != "wal":
            raise RuntimeError(f"detached backup lost WAL mode: {backup_wal_mode!r}")
        if backup_value_after_crash != 201:
            raise RuntimeError(
                f"uncommitted backup mutation leaked after crash: {backup_value_after_crash!r}"
            )
        if not backup_integrity_after_crash:
            raise RuntimeError("detached backup integrity_check failed after crash")
        if checkpoint_busy_after_crash:
            raise RuntimeError("detached backup checkpoint remained busy after crash recovery")

        writable = sqlite3.connect(backup, isolation_level=None, timeout=0.0)
        try:
            writable.execute("PRAGMA busy_timeout = 0")
            _write_value(writable, 204)
            backup_after_followup_commit = _read_value(writable)
            backup_integrity_after_followup = _integrity_ok(writable)
        finally:
            writable.close()

        reopened = sqlite3.connect(backup, isolation_level=None, timeout=0.0)
        try:
            final_backup_value = _read_value(reopened)
            final_backup_integrity = _integrity_ok(reopened)
        finally:
            reopened.close()

        if (
            backup_after_followup_commit != 204
            or not backup_integrity_after_followup
            or final_backup_value != 204
            or not final_backup_integrity
        ):
            raise RuntimeError("detached backup follow-up durability mismatch")

        payload = {
            "source_journal_mode": journal_mode,
            "source_value_before_backup": source_before_backup,
            "backup_initial_value": backup_initial_value,
            "backup_initial_integrity": "ok",
            "source_value_after_backup": source_after_backup,
            "backup_value_after_source_commit": backup_after_source_commit,
            "source_deleted": source_deleted,
            "uncommitted_backup_pending_value": 203,
            "uncommitted_backup_writer_forced_crash": True,
            "backup_wal_mode_after_crash": backup_wal_mode,
            "backup_value_after_crash": backup_value_after_crash,
            "backup_integrity_after_crash": "ok",
            "checkpoint_busy_after_crash": checkpoint_busy_after_crash,
            "backup_followup_commit": backup_after_followup_commit,
            "backup_integrity_after_followup": "ok",
            "final_backup_value": final_backup_value,
            "final_backup_integrity": "ok",
        }
        return (json.dumps(payload, separators=(",", ":")) + "\n").encode()


def main() -> int:
    if len(sys.argv) == 4 and sys.argv[1] == "--uncommitted-writer":
        try:
            return _uncommitted_writer(sys.argv[2], int(sys.argv[3]))
        except (OSError, RuntimeError, ValueError, sqlite3.Error) as exc:
            print(f"target_error: {exc}", file=sys.stderr)
            return 1
    if len(sys.argv) != 1:
        print("protocol_error: unexpected arguments", file=sys.stderr)
        return 2
    if sys.stdin.buffer.read(1):
        print(
            "protocol_error: WAL backup uncommitted crash target requires empty input",
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
