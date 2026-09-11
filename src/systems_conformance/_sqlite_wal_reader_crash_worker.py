from __future__ import annotations

import json
import pathlib
import sqlite3
import subprocess
import sys
import tempfile

_WORKER_MODULE = "systems_conformance._sqlite_wal_reader_crash_worker"


def _read_value(connection: sqlite3.Connection) -> int:
    row = connection.execute("SELECT v FROM items").fetchone()
    if row is None:
        raise RuntimeError("items row missing")
    return int(row[0])


def _checkpoint_busy(connection: sqlite3.Connection) -> bool:
    checkpoint = connection.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
    return not (
        checkpoint is not None and len(checkpoint) == 3 and int(checkpoint[0]) == 0
    )


def _reader(database: str, expected: int) -> int:
    connection = sqlite3.connect(database, isolation_level=None, timeout=0.0)
    try:
        connection.execute("PRAGMA busy_timeout = 0")
        mode = str(connection.execute("PRAGMA journal_mode").fetchone()[0]).lower()
        if mode != "wal":
            raise RuntimeError(f"reader WAL unavailable: {mode!r}")
        connection.execute("BEGIN")
        value = _read_value(connection)
        if value != expected:
            raise RuntimeError(f"reader initial value mismatch: {value!r}")
        print(f"READER_READY:{value}", flush=True)
        command = sys.stdin.readline().strip()
        if command != "READ":
            raise RuntimeError(f"reader expected READ command, got {command!r}")
        value = _read_value(connection)
        print(f"SNAPSHOT_VALUE:{value}", flush=True)
        while True:
            command = sys.stdin.readline()
            if command == "":
                raise RuntimeError("reader control pipe closed before forced crash")
    finally:
        connection.close()


def _start_reader(database: str, expected: int) -> subprocess.Popen[str]:
    process = subprocess.Popen(
        [sys.executable, "-m", _WORKER_MODULE, "--reader", database, str(expected)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if process.stdout is None:
        process.kill()
        process.communicate(timeout=2.0)
        raise RuntimeError("reader stdout pipe unavailable")
    marker = process.stdout.readline().strip()
    if marker != f"READER_READY:{expected}":
        if process.poll() is None:
            process.kill()
        _, stderr = process.communicate(timeout=2.0)
        raise RuntimeError(f"reader failed before snapshot: {marker!r} {stderr.strip()!r}")
    return process


def _read_snapshot(process: subprocess.Popen[str], expected: int) -> None:
    if process.stdin is None or process.stdout is None:
        raise RuntimeError("reader control pipes unavailable")
    process.stdin.write("READ\n")
    process.stdin.flush()
    marker = process.stdout.readline().strip()
    if marker != f"SNAPSHOT_VALUE:{expected}":
        raise RuntimeError(f"reader snapshot mismatch: {marker!r}")


def _kill_reader(process: subprocess.Popen[str]) -> None:
    try:
        process.kill()
        _, stderr = process.communicate(timeout=2.0)
        if process.returncode == 0:
            raise RuntimeError("reader unexpectedly exited successfully after forced kill")
        if stderr.strip():
            raise RuntimeError(f"reader emitted stderr before forced kill: {stderr.strip()!r}")
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate(timeout=2.0)


def _run() -> bytes:
    with tempfile.TemporaryDirectory(prefix="systems-conformance-wal-reader-crash-") as directory:
        database = str(pathlib.Path(directory) / "target.sqlite")
        connection = sqlite3.connect(database, isolation_level=None)
        try:
            connection.execute("CREATE TABLE items(v INTEGER NOT NULL)")
            connection.execute("INSERT INTO items VALUES (6)")
            mode = str(connection.execute("PRAGMA journal_mode = WAL").fetchone()[0]).lower()
            if mode != "wal":
                raise RuntimeError(f"WAL unavailable: {mode!r}")
            connection.execute("PRAGMA wal_autocheckpoint = 0")
        finally:
            connection.close()

        reader = _start_reader(database, 6)
        checkpoint_busy_while_reader_alive = False
        try:
            writer = sqlite3.connect(database, isolation_level=None, timeout=0.0)
            try:
                writer.execute("PRAGMA busy_timeout = 0")
                writer.execute("PRAGMA wal_autocheckpoint = 0")
                writer.execute("BEGIN IMMEDIATE")
                writer.execute("UPDATE items SET v = 8")
                writer.execute("COMMIT")
                if _read_value(writer) != 8:
                    raise RuntimeError("writer could not observe committed value")
            finally:
                writer.close()
            _read_snapshot(reader, 6)

            checkpoint_connection = sqlite3.connect(
                database, isolation_level=None, timeout=0.0
            )
            try:
                checkpoint_connection.execute("PRAGMA busy_timeout = 0")
                checkpoint_busy_while_reader_alive = _checkpoint_busy(
                    checkpoint_connection
                )
            finally:
                checkpoint_connection.close()
            if not checkpoint_busy_while_reader_alive:
                raise RuntimeError(
                    "truncating checkpoint unexpectedly completed while reader snapshot was pinned"
                )

            _kill_reader(reader)
        finally:
            if reader.poll() is None:
                reader.kill()
                reader.communicate(timeout=2.0)

        reopened = sqlite3.connect(database, isolation_level=None, timeout=0.0)
        try:
            reopened.execute("PRAGMA busy_timeout = 0")
            reopened.execute("PRAGMA wal_autocheckpoint = 0")
            journal_mode = str(reopened.execute("PRAGMA journal_mode").fetchone()[0]).lower()
            recovered_value = _read_value(reopened)
            integrity = reopened.execute("PRAGMA integrity_check").fetchall() == [("ok",)]
            reopened.execute("BEGIN IMMEDIATE")
            reopened.execute("UPDATE items SET v = 9")
            reopened.execute("COMMIT")
            post_crash_write_value = _read_value(reopened)
        finally:
            reopened.close()

        verified = sqlite3.connect(database, isolation_level=None, timeout=0.0)
        try:
            verified.execute("PRAGMA busy_timeout = 0")
            durable_value = _read_value(verified)
            checkpoint_busy_after_reader_crash = _checkpoint_busy(verified)
        finally:
            verified.close()

        if (
            journal_mode != "wal"
            or recovered_value != 8
            or not integrity
            or post_crash_write_value != 9
            or durable_value != 9
            or checkpoint_busy_after_reader_crash
        ):
            raise RuntimeError(
                "post-reader-crash recovery mismatch: "
                f"mode={journal_mode!r} recovered={recovered_value!r} integrity={integrity!r} "
                f"post_write={post_crash_write_value!r} durable={durable_value!r} "
                f"checkpoint_busy_after_crash={checkpoint_busy_after_reader_crash!r}"
            )
        payload = {
            "journal_mode": journal_mode,
            "reader_initial_value": 6,
            "writer_committed_value": 8,
            "reader_snapshot_after_commit": 6,
            "checkpoint_busy_while_reader_alive": checkpoint_busy_while_reader_alive,
            "reader_forced_crash": True,
            "fresh_reopen_value": recovered_value,
            "fresh_reopen_integrity": "ok",
            "post_reader_crash_write_value": post_crash_write_value,
            "post_reader_crash_write_durable": durable_value,
            "fresh_reopen_checkpoint_busy": checkpoint_busy_after_reader_crash,
        }
        return (json.dumps(payload, separators=(",", ":")) + "\n").encode()


def main() -> int:
    if len(sys.argv) == 4 and sys.argv[1] == "--reader":
        try:
            return _reader(sys.argv[2], int(sys.argv[3]))
        except (OSError, RuntimeError, ValueError, sqlite3.Error) as exc:
            print(f"target_error: {exc}", file=sys.stderr)
            return 1
    if len(sys.argv) != 1:
        print("protocol_error: unexpected arguments", file=sys.stderr)
        return 2
    if sys.stdin.buffer.read(1):
        print("protocol_error: WAL reader crash target requires empty input", file=sys.stderr)
        return 2
    try:
        sys.stdout.buffer.write(_run())
    except (OSError, RuntimeError, sqlite3.Error, subprocess.SubprocessError) as exc:
        print(f"target_error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
