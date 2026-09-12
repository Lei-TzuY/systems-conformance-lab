from __future__ import annotations

import json
import pathlib
import sqlite3
import subprocess
import sys
import tempfile

from systems_conformance._sqlite_wal_reader_crash_worker import (
    _checkpoint_busy,
    _kill_reader,
    _read_snapshot,
    _read_value,
    _start_reader,
)


def _run() -> bytes:
    with tempfile.TemporaryDirectory(prefix="systems-conformance-wal-reader-crash-rollback-") as directory:
        database = str(pathlib.Path(directory) / "target.sqlite")
        connection = sqlite3.connect(database, isolation_level=None)
        try:
            connection.execute("CREATE TABLE items(v INTEGER NOT NULL)")
            connection.execute("INSERT INTO items VALUES (10)")
            mode = str(connection.execute("PRAGMA journal_mode = WAL").fetchone()[0]).lower()
            if mode != "wal":
                raise RuntimeError(f"WAL unavailable: {mode!r}")
            connection.execute("PRAGMA wal_autocheckpoint = 0")
        finally:
            connection.close()

        reader = _start_reader(database, 10)
        writer = sqlite3.connect(database, isolation_level=None, timeout=0.0)
        try:
            writer.execute("PRAGMA busy_timeout = 0")
            writer.execute("PRAGMA wal_autocheckpoint = 0")
            writer.execute("BEGIN IMMEDIATE")
            writer.execute("UPDATE items SET v = 11")
            _read_snapshot(reader, 10)
            _kill_reader(reader)
            writer.execute("ROLLBACK")
            writer_value_after_rollback = _read_value(writer)
            if writer_value_after_rollback != 10:
                raise RuntimeError("writer rollback did not restore committed value")
        finally:
            if reader.poll() is None:
                reader.kill()
                reader.communicate(timeout=2.0)
            if writer.in_transaction:
                writer.execute("ROLLBACK")
            writer.close()

        reopened = sqlite3.connect(database, isolation_level=None, timeout=0.0)
        try:
            reopened.execute("PRAGMA busy_timeout = 0")
            reopened.execute("PRAGMA wal_autocheckpoint = 0")
            durable_after_rollback = _read_value(reopened)
            integrity_after_rollback = reopened.execute("PRAGMA integrity_check").fetchall() == [("ok",)]
            checkpoint_busy_after_rollback = _checkpoint_busy(reopened)
            reopened.execute("BEGIN IMMEDIATE")
            reopened.execute("UPDATE items SET v = 12")
            reopened.execute("COMMIT")
            post_rollback_write = _read_value(reopened)
        finally:
            reopened.close()

        verified = sqlite3.connect(database, isolation_level=None, timeout=0.0)
        try:
            verified.execute("PRAGMA busy_timeout = 0")
            final_durable_value = _read_value(verified)
            final_integrity = verified.execute("PRAGMA integrity_check").fetchall() == [("ok",)]
            final_checkpoint_busy = _checkpoint_busy(verified)
        finally:
            verified.close()

        if (
            durable_after_rollback != 10
            or not integrity_after_rollback
            or checkpoint_busy_after_rollback
            or post_rollback_write != 12
            or final_durable_value != 12
            or not final_integrity
            or final_checkpoint_busy
        ):
            raise RuntimeError(
                "reader-crash writer-rollback recovery mismatch: "
                f"rollback={durable_after_rollback!r} integrity={integrity_after_rollback!r} "
                f"checkpoint_busy={checkpoint_busy_after_rollback!r} post_write={post_rollback_write!r} "
                f"durable={final_durable_value!r} final_integrity={final_integrity!r} "
                f"final_checkpoint_busy={final_checkpoint_busy!r}"
            )

        payload = {
            "journal_mode": mode,
            "reader_initial_value": 10,
            "writer_pending_value": 11,
            "reader_snapshot_while_writer_active": 10,
            "reader_forced_crash": True,
            "writer_value_after_rollback": writer_value_after_rollback,
            "fresh_reopen_value_after_rollback": durable_after_rollback,
            "fresh_reopen_integrity_after_rollback": "ok",
            "fresh_reopen_checkpoint_busy_after_rollback": checkpoint_busy_after_rollback,
            "post_rollback_write_value": post_rollback_write,
            "final_durable_value": final_durable_value,
            "final_integrity": "ok",
            "final_checkpoint_busy": final_checkpoint_busy,
        }
        return (json.dumps(payload, separators=(",", ":")) + "\n").encode()


def main() -> int:
    if len(sys.argv) != 1:
        print("protocol_error: unexpected arguments", file=sys.stderr)
        return 2
    if sys.stdin.buffer.read(1):
        print("protocol_error: WAL reader crash rollback target requires empty input", file=sys.stderr)
        return 2
    try:
        sys.stdout.buffer.write(_run())
    except (OSError, RuntimeError, sqlite3.Error, subprocess.SubprocessError) as exc:
        print(f"target_error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
