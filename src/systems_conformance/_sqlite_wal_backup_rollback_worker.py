from __future__ import annotations

import json
import pathlib
import sqlite3
import subprocess
import sys
import tempfile
import time

_WORKER_MODULE = "systems_conformance._sqlite_wal_backup_rollback_worker"


def _read_value(connection: sqlite3.Connection) -> int:
    row = connection.execute("SELECT v FROM items").fetchone()
    if row is None:
        raise RuntimeError("items row missing")
    return int(row[0])


def _integrity_ok(connection: sqlite3.Connection) -> bool:
    return connection.execute("PRAGMA integrity_check").fetchall() == [("ok",)]


def _uncommitted_writer(database: str) -> int:
    connection = sqlite3.connect(database, isolation_level=None, timeout=0.0)
    try:
        connection.execute("PRAGMA busy_timeout = 0")
        row = connection.execute("PRAGMA journal_mode = WAL").fetchone()
        actual = None if row is None else str(row[0]).lower()
        if actual != "wal":
            raise RuntimeError(f"detached backup WAL unavailable: got {actual}")
        connection.execute("PRAGMA wal_autocheckpoint = 0")
        connection.execute("BEGIN IMMEDIATE")
        connection.execute("UPDATE items SET v = 7")
        if _read_value(connection) != 7:
            raise RuntimeError("uncommitted writer could not observe its mutation")
        print("UNCOMMITTED_READY", flush=True)
        while True:
            time.sleep(60.0)
    finally:
        connection.close()


def _committed_writer(database: str, committed_value: int) -> int:
    connection = sqlite3.connect(database, isolation_level=None, timeout=0.0)
    try:
        connection.execute("PRAGMA busy_timeout = 0")
        row = connection.execute("PRAGMA journal_mode = WAL").fetchone()
        actual = None if row is None else str(row[0]).lower()
        if actual != "wal":
            raise RuntimeError(f"recovered backup WAL unavailable: got {actual}")
        connection.execute("PRAGMA wal_autocheckpoint = 0")
        connection.execute("BEGIN IMMEDIATE")
        connection.execute("UPDATE items SET v = ?", (committed_value,))
        connection.execute("COMMIT")
        if _read_value(connection) != committed_value:
            raise RuntimeError("committed writer could not observe its durable mutation")
        print(f"COMMITTED_READY:{committed_value}", flush=True)
        while True:
            time.sleep(60.0)
    finally:
        connection.close()


def _verify_reopen(database: str, expected_value: int) -> int:
    connection = sqlite3.connect(database, isolation_level=None, timeout=0.0)
    try:
        connection.execute("PRAGMA busy_timeout = 0")
        row = connection.execute("PRAGMA journal_mode").fetchone()
        journal_mode = None if row is None else str(row[0]).lower()
        value = _read_value(connection)
        integrity = "ok" if _integrity_ok(connection) else "failed"
        checkpoint = connection.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
        checkpoint_busy = not (
            checkpoint is not None and len(checkpoint) == 3 and int(checkpoint[0]) == 0
        )
    finally:
        connection.close()

    if journal_mode != "wal":
        raise RuntimeError(f"fresh reopen did not retain WAL mode: {journal_mode!r}")
    if value != expected_value:
        raise RuntimeError(
            f"fresh reopen lost post-rollback commit: expected {expected_value}, got {value}"
        )
    if integrity != "ok":
        raise RuntimeError("fresh reopen integrity_check failed")
    if checkpoint_busy:
        raise RuntimeError("fresh reopen checkpoint remained busy")

    print(
        json.dumps(
            {
                "journal_mode": journal_mode,
                "value": value,
                "integrity": integrity,
                "checkpoint_busy": checkpoint_busy,
            },
            separators=(",", ":"),
        ),
        flush=True,
    )
    return 0


def _force_kill_uncommitted(database: str) -> None:
    process = subprocess.Popen(
        [sys.executable, "-m", _WORKER_MODULE, "--uncommitted-writer", database],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        if process.stdout is None:
            raise RuntimeError("uncommitted writer stdout pipe unavailable")
        marker = process.stdout.readline().strip()
        if marker != "UNCOMMITTED_READY":
            stderr = "" if process.stderr is None else process.stderr.read().strip()
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


def _force_kill_committed(database: str, committed_value: int) -> None:
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            _WORKER_MODULE,
            "--committed-writer",
            database,
            str(committed_value),
        ],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        if process.stdout is None:
            raise RuntimeError("committed writer stdout pipe unavailable")
        marker = process.stdout.readline().strip()
        expected_marker = f"COMMITTED_READY:{committed_value}"
        if marker != expected_marker:
            stderr = "" if process.stderr is None else process.stderr.read().strip()
            raise RuntimeError(
                "committed writer failed before forced crash: "
                f"marker={marker!r} stderr={stderr!r}"
            )
        process.kill()
        _, stderr = process.communicate(timeout=2.0)
        if process.returncode == 0:
            raise RuntimeError(
                "committed writer unexpectedly exited successfully after forced kill"
            )
        if stderr.strip():
            raise RuntimeError(
                f"committed writer emitted stderr before forced kill: {stderr.strip()!r}"
            )
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate(timeout=2.0)


def _fresh_reopen(database: str, expected_value: int) -> dict[str, object]:
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            _WORKER_MODULE,
            "--verify-reopen",
            database,
            str(expected_value),
        ],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=3.0,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            "fresh reopen verifier failed: "
            f"exit={completed.returncode} stderr={completed.stderr.strip()!r}"
        )
    if completed.stderr.strip():
        raise RuntimeError(
            f"fresh reopen verifier emitted stderr: {completed.stderr.strip()!r}"
        )
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("fresh reopen verifier emitted invalid JSON") from exc
    if not isinstance(payload, dict):
        raise TypeError("fresh reopen verifier emitted non-object JSON")
    return payload


def _run() -> bytes:
    with tempfile.TemporaryDirectory(
        prefix="systems-conformance-sqlite-wal-backup-rollback-"
    ) as directory:
        root = pathlib.Path(directory)
        source_path = str(root / "source.sqlite")
        backup_path = str(root / "backup.sqlite")

        source = sqlite3.connect(source_path, isolation_level=None)
        try:
            source.execute("CREATE TABLE items(v INTEGER NOT NULL)")
            source.execute("INSERT INTO items VALUES (6)")
            backup = sqlite3.connect(backup_path, isolation_level=None)
            try:
                source.backup(backup)
            finally:
                backup.close()
        finally:
            source.close()

        for path in (source_path, f"{source_path}-wal", f"{source_path}-shm"):
            try:
                pathlib.Path(path).unlink()
            except FileNotFoundError:
                pass
        if pathlib.Path(source_path).exists():
            raise RuntimeError("source database remained after deletion boundary")

        _force_kill_uncommitted(backup_path)

        recovered = sqlite3.connect(backup_path, isolation_level=None, timeout=0.0)
        try:
            recovered.execute("PRAGMA busy_timeout = 0")
            row = recovered.execute("PRAGMA journal_mode").fetchone()
            journal_mode = None if row is None else str(row[0]).lower()
            recovered_value = _read_value(recovered)
            integrity = "ok" if _integrity_ok(recovered) else "failed"
            checkpoint = recovered.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
            checkpoint_busy = not (
                checkpoint is not None
                and len(checkpoint) == 3
                and int(checkpoint[0]) == 0
            )
        finally:
            recovered.close()

        if journal_mode != "wal":
            raise RuntimeError(f"detached backup did not retain WAL mode: {journal_mode!r}")
        if recovered_value != 6:
            raise RuntimeError(f"uncommitted crash leaked value: {recovered_value!r}")
        if integrity != "ok":
            raise RuntimeError("integrity_check failed after uncommitted crash")
        if checkpoint_busy:
            raise RuntimeError("checkpoint remained busy after uncommitted crash")

        post_rollback_committed_value = 8
        _force_kill_committed(backup_path, post_rollback_committed_value)

        reopened = _fresh_reopen(backup_path, post_rollback_committed_value)
        if reopened != {
            "journal_mode": "wal",
            "value": post_rollback_committed_value,
            "integrity": "ok",
            "checkpoint_busy": False,
        }:
            raise RuntimeError(f"fresh reopen verification mismatch: {reopened!r}")

        payload = {
            "source_deleted": True,
            "backup_process": "detached",
            "journal_mode": journal_mode,
            "uncommitted_writer_terminated": True,
            "recovered_value": recovered_value,
            "integrity": integrity,
            "checkpoint_busy": checkpoint_busy,
            "post_rollback_committed_value": post_rollback_committed_value,
            "post_rollback_committed_writer_terminated": True,
            "fresh_reopen_value": reopened["value"],
            "fresh_reopen_integrity": reopened["integrity"],
            "fresh_reopen_checkpoint_busy": reopened["checkpoint_busy"],
        }
        return (json.dumps(payload, separators=(",", ":")) + "\n").encode()


def main() -> int:
    if len(sys.argv) == 3 and sys.argv[1] == "--uncommitted-writer":
        try:
            return _uncommitted_writer(sys.argv[2])
        except (OSError, RuntimeError, sqlite3.Error) as exc:
            print(f"target_error: {exc}", file=sys.stderr)
            return 1
    if len(sys.argv) == 4 and sys.argv[1] == "--committed-writer":
        try:
            committed_value = int(sys.argv[3])
            return _committed_writer(sys.argv[2], committed_value)
        except (OSError, RuntimeError, ValueError, sqlite3.Error) as exc:
            print(f"target_error: {exc}", file=sys.stderr)
            return 1
    if len(sys.argv) == 4 and sys.argv[1] == "--verify-reopen":
        try:
            expected_value = int(sys.argv[3])
            return _verify_reopen(sys.argv[2], expected_value)
        except (OSError, RuntimeError, TypeError, ValueError, sqlite3.Error) as exc:
            print(f"target_error: {exc}", file=sys.stderr)
            return 1
    if len(sys.argv) != 1:
        print("protocol_error: unexpected arguments", file=sys.stderr)
        return 2
    if sys.stdin.buffer.read(1):
        print(
            "protocol_error: SQLite WAL backup rollback target requires empty input",
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
