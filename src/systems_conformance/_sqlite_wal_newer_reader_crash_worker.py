from __future__ import annotations

import json
import pathlib
import sqlite3
import subprocess
import sys
import tempfile

from ._sqlite_wal_multi_reader_crash_worker import _checkpoint_is_busy, _commit_value
from ._sqlite_wal_reader_crash_worker import _kill_reader, _read_snapshot, _read_value, _start_reader


def _run() -> bytes:
    with tempfile.TemporaryDirectory(prefix="systems-conformance-wal-newer-reader-crash-") as directory:
        database = str(pathlib.Path(directory) / "target.sqlite")
        connection = sqlite3.connect(database, isolation_level=None)
        try:
            connection.execute("CREATE TABLE items(v INTEGER NOT NULL)")
            connection.execute("INSERT INTO items VALUES (20)")
            journal_mode = str(connection.execute("PRAGMA journal_mode = WAL").fetchone()[0]).lower()
            if journal_mode != "wal":
                raise RuntimeError(f"WAL unavailable: {journal_mode!r}")
            connection.execute("PRAGMA wal_autocheckpoint = 0")
        finally:
            connection.close()

        older_reader = _start_reader(database, 20)
        newer_reader: subprocess.Popen[str] | None = None
        try:
            first_commit = _commit_value(database, 21)
            _read_snapshot(older_reader, 20)
            newer_reader = _start_reader(database, 21)
            second_commit = _commit_value(database, 22)
            _read_snapshot(newer_reader, 21)

            busy_with_two = _checkpoint_is_busy(database)
            if not busy_with_two:
                raise RuntimeError("checkpoint unexpectedly completed with two pinned readers")

            _kill_reader(newer_reader)
            _read_snapshot(older_reader, 20)
            busy_after_newer_crash = _checkpoint_is_busy(database)
            if not busy_after_newer_crash:
                raise RuntimeError("newer reader crash incorrectly released older reader checkpoint state")

            _kill_reader(older_reader)
            busy_after_final_crash = _checkpoint_is_busy(database)
            if busy_after_final_crash:
                raise RuntimeError("checkpoint remained busy after final reader crash")
        finally:
            if older_reader.poll() is None:
                older_reader.kill()
                older_reader.communicate(timeout=2.0)
            if newer_reader is not None and newer_reader.poll() is None:
                newer_reader.kill()
                newer_reader.communicate(timeout=2.0)

        post_crash_write = _commit_value(database, 23)
        verified = sqlite3.connect(database, isolation_level=None, timeout=0.0)
        try:
            verified.execute("PRAGMA busy_timeout = 0")
            durable_value = _read_value(verified)
            integrity = verified.execute("PRAGMA integrity_check").fetchall() == [("ok",)]
            final_busy = _checkpoint_is_busy(database)
        finally:
            verified.close()

        if post_crash_write != 23 or durable_value != 23 or not integrity or final_busy:
            raise RuntimeError("newer-reader crash recovery did not preserve durable write/checkpoint state")

        return (json.dumps({
            "journal_mode": journal_mode,
            "older_reader_snapshot": 20,
            "first_writer_committed_value": first_commit,
            "newer_reader_snapshot": 21,
            "second_writer_committed_value": second_commit,
            "checkpoint_busy_with_two_readers": busy_with_two,
            "newer_reader_forced_crash": True,
            "older_reader_snapshot_after_newer_crash": 20,
            "checkpoint_busy_after_newer_reader_crash": busy_after_newer_crash,
            "older_reader_forced_crash": True,
            "checkpoint_busy_after_final_reader_crash": busy_after_final_crash,
            "post_crash_write_value": post_crash_write,
            "fresh_reopen_value": durable_value,
            "fresh_reopen_integrity": "ok",
            "fresh_reopen_checkpoint_busy": final_busy,
        }, separators=(",", ":")) + "\n").encode()


def main() -> int:
    if len(sys.argv) != 1:
        print("protocol_error: unexpected arguments", file=sys.stderr)
        return 2
    if sys.stdin.buffer.read(1):
        print("protocol_error: WAL newer-reader crash target requires empty input", file=sys.stderr)
        return 2
    try:
        sys.stdout.buffer.write(_run())
    except (OSError, RuntimeError, sqlite3.Error, subprocess.SubprocessError) as exc:
        print(f"target_error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
