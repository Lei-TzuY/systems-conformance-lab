from __future__ import annotations

import json
import pathlib
import sqlite3
import subprocess
import sys
import tempfile

from ._sqlite_wal_reader_crash_worker import (
    _checkpoint_busy,
    _kill_reader,
    _read_snapshot,
    _read_value,
    _start_reader,
)


def _commit_value(database: str, value: int) -> int:
    connection = sqlite3.connect(database, isolation_level=None, timeout=0.0)
    try:
        connection.execute("PRAGMA busy_timeout = 0")
        connection.execute("PRAGMA wal_autocheckpoint = 0")
        connection.execute("BEGIN IMMEDIATE")
        connection.execute("UPDATE items SET v = ?", (value,))
        connection.execute("COMMIT")
        observed = _read_value(connection)
        if observed != value:
            raise RuntimeError(
                f"writer could not observe committed value: {observed!r} != {value!r}"
            )
        return observed
    finally:
        if connection.in_transaction:
            connection.execute("ROLLBACK")
        connection.close()


def _checkpoint_is_busy(database: str) -> bool:
    connection = sqlite3.connect(database, isolation_level=None, timeout=0.0)
    try:
        connection.execute("PRAGMA busy_timeout = 0")
        return _checkpoint_busy(connection)
    finally:
        connection.close()


def _run() -> bytes:
    with tempfile.TemporaryDirectory(
        prefix="systems-conformance-wal-multi-reader-crash-"
    ) as directory:
        database = str(pathlib.Path(directory) / "target.sqlite")
        connection = sqlite3.connect(database, isolation_level=None)
        try:
            connection.execute("CREATE TABLE items(v INTEGER NOT NULL)")
            connection.execute("INSERT INTO items VALUES (10)")
            journal_mode = str(
                connection.execute("PRAGMA journal_mode = WAL").fetchone()[0]
            ).lower()
            if journal_mode != "wal":
                raise RuntimeError(f"WAL unavailable: {journal_mode!r}")
            connection.execute("PRAGMA wal_autocheckpoint = 0")
        finally:
            connection.close()

        older_reader = _start_reader(database, 10)
        newer_reader: subprocess.Popen[str] | None = None
        try:
            first_commit = _commit_value(database, 11)
            _read_snapshot(older_reader, 10)

            newer_reader = _start_reader(database, 11)
            second_commit = _commit_value(database, 12)
            _read_snapshot(newer_reader, 11)

            checkpoint_busy_with_two_readers = _checkpoint_is_busy(database)
            if not checkpoint_busy_with_two_readers:
                raise RuntimeError(
                    "truncating checkpoint unexpectedly completed with two pinned readers"
                )

            _kill_reader(older_reader)
            checkpoint_busy_after_older_crash = _checkpoint_is_busy(database)
            if not checkpoint_busy_after_older_crash:
                raise RuntimeError(
                    "killing older reader incorrectly released surviving reader checkpoint state"
                )

            _kill_reader(newer_reader)
            checkpoint_busy_after_final_crash = _checkpoint_is_busy(database)
            if checkpoint_busy_after_final_crash:
                raise RuntimeError(
                    "truncating checkpoint remained busy after final reader crash"
                )
        finally:
            if older_reader.poll() is None:
                older_reader.kill()
                older_reader.communicate(timeout=2.0)
            if newer_reader is not None and newer_reader.poll() is None:
                newer_reader.kill()
                newer_reader.communicate(timeout=2.0)

        post_crash_write = _commit_value(database, 13)

        verified = sqlite3.connect(database, isolation_level=None, timeout=0.0)
        try:
            verified.execute("PRAGMA busy_timeout = 0")
            durable_value = _read_value(verified)
            integrity = verified.execute("PRAGMA integrity_check").fetchall() == [("ok",)]
            final_checkpoint_busy = _checkpoint_busy(verified)
        finally:
            verified.close()

        if (
            first_commit != 11
            or second_commit != 12
            or post_crash_write != 13
            or durable_value != 13
            or not integrity
            or final_checkpoint_busy
        ):
            raise RuntimeError(
                "multi-reader crash recovery mismatch: "
                f"first_commit={first_commit!r} second_commit={second_commit!r} "
                f"post_crash_write={post_crash_write!r} durable={durable_value!r} "
                f"integrity={integrity!r} final_checkpoint_busy={final_checkpoint_busy!r}"
            )

        payload = {
            "journal_mode": journal_mode,
            "older_reader_snapshot": 10,
            "first_writer_committed_value": first_commit,
            "newer_reader_snapshot": 11,
            "second_writer_committed_value": second_commit,
            "checkpoint_busy_with_two_readers": checkpoint_busy_with_two_readers,
            "older_reader_forced_crash": True,
            "checkpoint_busy_after_older_reader_crash": checkpoint_busy_after_older_crash,
            "newer_reader_forced_crash": True,
            "checkpoint_busy_after_final_reader_crash": checkpoint_busy_after_final_crash,
            "post_crash_write_value": post_crash_write,
            "fresh_reopen_value": durable_value,
            "fresh_reopen_integrity": "ok",
            "fresh_reopen_checkpoint_busy": final_checkpoint_busy,
        }
        return (json.dumps(payload, separators=(",", ":")) + "\n").encode()


def main() -> int:
    if len(sys.argv) != 1:
        print("protocol_error: unexpected arguments", file=sys.stderr)
        return 2
    if sys.stdin.buffer.read(1):
        print(
            "protocol_error: WAL multi-reader crash target requires empty input",
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
