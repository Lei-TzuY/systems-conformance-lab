from __future__ import annotations

import json
import pathlib
import sqlite3
import subprocess
import sys
import tempfile

from ._sqlite_wal_backup_recovery_worker import _integrity_ok, _read_value, _write_value
from ._sqlite_wal_multi_reader_crash_worker import _checkpoint_is_busy, _commit_value
from ._sqlite_wal_newer_reader_crash_worker import _start_reader
from ._sqlite_wal_partial_release_committed_writer_crash_worker import (
    _kill_writer,
    _start_committed_writer,
)
from ._sqlite_wal_reader_crash_worker import _kill_reader, _read_snapshot


def _run() -> bytes:
    with tempfile.TemporaryDirectory(
        prefix="systems-conformance-wal-pinned-reader-backup-"
    ) as directory:
        root = pathlib.Path(directory)
        database = str(root / "source.sqlite")
        backup = str(root / "backup.sqlite")

        connection = sqlite3.connect(database, isolation_level=None)
        try:
            connection.execute("CREATE TABLE items(v INTEGER NOT NULL)")
            connection.execute("INSERT INTO items VALUES (90)")
            journal_mode = str(connection.execute("PRAGMA journal_mode = WAL").fetchone()[0]).lower()
            if journal_mode != "wal":
                raise RuntimeError(f"WAL unavailable: {journal_mode!r}")
            connection.execute("PRAGMA wal_autocheckpoint = 0")
        finally:
            connection.close()

        reader = _start_reader(database, 90)
        writer: subprocess.Popen[str] | None = None
        try:
            first_commit = _commit_value(database, 91)
            _read_snapshot(reader, 90)

            writer = _start_committed_writer(database, 92)
            _kill_writer(writer)
            writer = None

            _read_snapshot(reader, 90)
            observer = sqlite3.connect(database, isolation_level=None, timeout=0.0)
            try:
                observer.execute("PRAGMA busy_timeout = 0")
                source_after_writer_crash = _read_value(observer)
            finally:
                observer.close()
            if source_after_writer_crash != 92:
                raise RuntimeError(
                    f"committed value lost after writer crash: {source_after_writer_crash!r}"
                )

            checkpoint_busy_before_backup = _checkpoint_is_busy(database)
            if not checkpoint_busy_before_backup:
                raise RuntimeError("checkpoint unexpectedly completed with pinned reader")

            source = sqlite3.connect(database, isolation_level=None, timeout=0.0)
            destination = sqlite3.connect(backup, isolation_level=None, timeout=0.0)
            try:
                source.execute("PRAGMA busy_timeout = 0")
                source.backup(destination)
                backup_value_while_reader_pinned = _read_value(destination)
                backup_integrity_while_reader_pinned = _integrity_ok(destination)
            finally:
                destination.close()
                source.close()
            if backup_value_while_reader_pinned != 92:
                raise RuntimeError(
                    "online backup captured stale reader snapshot: "
                    f"{backup_value_while_reader_pinned!r}"
                )
            if not backup_integrity_while_reader_pinned:
                raise RuntimeError("backup integrity_check failed while source reader was pinned")

            _read_snapshot(reader, 90)
            checkpoint_busy_after_backup = _checkpoint_is_busy(database)
            if not checkpoint_busy_after_backup:
                raise RuntimeError("backup incorrectly released pinned reader checkpoint state")

            second_commit = _commit_value(database, 93)
            _read_snapshot(reader, 90)
            observer = sqlite3.connect(database, isolation_level=None, timeout=0.0)
            backup_connection = sqlite3.connect(backup, isolation_level=None, timeout=0.0)
            try:
                observer.execute("PRAGMA busy_timeout = 0")
                source_after_post_backup_commit = _read_value(observer)
                backup_after_source_commit = _read_value(backup_connection)
            finally:
                backup_connection.close()
                observer.close()
            if source_after_post_backup_commit != 93 or backup_after_source_commit != 92:
                raise RuntimeError(
                    "source/backup independence mismatch after source commit: "
                    f"source={source_after_post_backup_commit!r} "
                    f"backup={backup_after_source_commit!r}"
                )

            checkpoint_busy_after_source_commit = _checkpoint_is_busy(database)
            if not checkpoint_busy_after_source_commit:
                raise RuntimeError("checkpoint unexpectedly completed with reader still pinned")

            _kill_reader(reader)
            checkpoint_busy_after_reader_release = _checkpoint_is_busy(database)
            if checkpoint_busy_after_reader_release:
                raise RuntimeError("checkpoint remained busy after final reader release")
        finally:
            if writer is not None and writer.poll() is None:
                _kill_writer(writer)
            if reader.poll() is None:
                _kill_reader(reader)

        source_reopen = sqlite3.connect(database, isolation_level=None, timeout=0.0)
        backup_reopen = sqlite3.connect(backup, isolation_level=None, timeout=0.0)
        try:
            source_reopen.execute("PRAGMA busy_timeout = 0")
            backup_reopen.execute("PRAGMA busy_timeout = 0")
            source_reopen_value = _read_value(source_reopen)
            backup_reopen_value = _read_value(backup_reopen)
            source_integrity = _integrity_ok(source_reopen)
            backup_integrity = _integrity_ok(backup_reopen)
            _write_value(backup_reopen, 94)
            backup_after_backup_write = _read_value(backup_reopen)
            source_after_backup_write = _read_value(source_reopen)
        finally:
            backup_reopen.close()
            source_reopen.close()

        if (
            first_commit != 91
            or second_commit != 93
            or source_reopen_value != 93
            or backup_reopen_value != 92
            or not source_integrity
            or not backup_integrity
            or backup_after_backup_write != 94
            or source_after_backup_write != 93
        ):
            raise RuntimeError("pinned-reader backup recovery mismatch")

        source_followup = _commit_value(database, 95)
        backup_verify = sqlite3.connect(backup, isolation_level=None, timeout=0.0)
        source_verify = sqlite3.connect(database, isolation_level=None, timeout=0.0)
        try:
            final_backup_value = _read_value(backup_verify)
            final_source_value = _read_value(source_verify)
            final_backup_integrity = _integrity_ok(backup_verify)
            final_source_integrity = _integrity_ok(source_verify)
        finally:
            source_verify.close()
            backup_verify.close()
        if (
            source_followup != 95
            or final_source_value != 95
            or final_backup_value != 94
            or not final_source_integrity
            or not final_backup_integrity
        ):
            raise RuntimeError("post-release source/backup durability mismatch")

        payload = {
            "journal_mode": journal_mode,
            "reader_snapshot": 90,
            "first_writer_committed_value": first_commit,
            "committed_writer_value": 92,
            "committed_writer_forced_crash": True,
            "reader_snapshot_after_writer_crash": 90,
            "fresh_source_value_after_writer_crash": source_after_writer_crash,
            "checkpoint_busy_before_backup": checkpoint_busy_before_backup,
            "backup_value_while_reader_pinned": backup_value_while_reader_pinned,
            "backup_integrity_while_reader_pinned": "ok",
            "reader_snapshot_after_backup": 90,
            "checkpoint_busy_after_backup": checkpoint_busy_after_backup,
            "second_writer_committed_value": second_commit,
            "reader_snapshot_after_source_commit": 90,
            "fresh_source_value_after_backup_commit": source_after_post_backup_commit,
            "backup_value_after_source_commit": backup_after_source_commit,
            "checkpoint_busy_after_source_commit": checkpoint_busy_after_source_commit,
            "reader_forced_release": True,
            "checkpoint_busy_after_reader_release": checkpoint_busy_after_reader_release,
            "source_reopen_value": source_reopen_value,
            "backup_reopen_value": backup_reopen_value,
            "source_reopen_integrity": "ok",
            "backup_reopen_integrity": "ok",
            "backup_after_backup_write": backup_after_backup_write,
            "source_after_backup_write": source_after_backup_write,
            "source_followup_commit": source_followup,
            "final_source_value": final_source_value,
            "final_backup_value": final_backup_value,
            "final_source_integrity": "ok",
            "final_backup_integrity": "ok",
        }
        return (json.dumps(payload, separators=(",", ":")) + "\n").encode()


def main() -> int:
    if len(sys.argv) != 1:
        print("protocol_error: unexpected arguments", file=sys.stderr)
        return 2
    if sys.stdin.buffer.read(1):
        print(
            "protocol_error: WAL pinned-reader backup target requires empty input",
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
