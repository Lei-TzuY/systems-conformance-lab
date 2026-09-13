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
        prefix="systems-conformance-wal-multi-reader-backup-"
    ) as directory:
        root = pathlib.Path(directory)
        database = str(root / "source.sqlite")
        backup = str(root / "backup.sqlite")

        connection = sqlite3.connect(database, isolation_level=None)
        try:
            connection.execute("CREATE TABLE items(v INTEGER NOT NULL)")
            connection.execute("INSERT INTO items VALUES (110)")
            journal_mode = str(connection.execute("PRAGMA journal_mode = WAL").fetchone()[0]).lower()
            if journal_mode != "wal":
                raise RuntimeError(f"WAL unavailable: {journal_mode!r}")
            connection.execute("PRAGMA wal_autocheckpoint = 0")
        finally:
            connection.close()

        older_reader = _start_reader(database, 110)
        newer_reader: subprocess.Popen[str] | None = None
        writer: subprocess.Popen[str] | None = None
        try:
            first_commit = _commit_value(database, 111)
            _read_snapshot(older_reader, 110)
            newer_reader = _start_reader(database, 111)

            writer = _start_committed_writer(database, 112)
            _kill_writer(writer)
            writer = None

            _read_snapshot(older_reader, 110)
            _read_snapshot(newer_reader, 111)
            observer = sqlite3.connect(database, isolation_level=None, timeout=0.0)
            try:
                observer.execute("PRAGMA busy_timeout = 0")
                source_after_writer_crash = _read_value(observer)
            finally:
                observer.close()
            if source_after_writer_crash != 112:
                raise RuntimeError(
                    f"committed value lost after writer crash: {source_after_writer_crash!r}"
                )

            checkpoint_busy_before_backup = _checkpoint_is_busy(database)
            if not checkpoint_busy_before_backup:
                raise RuntimeError("checkpoint unexpectedly completed with two pinned readers")

            source = sqlite3.connect(database, isolation_level=None, timeout=0.0)
            destination = sqlite3.connect(backup, isolation_level=None, timeout=0.0)
            try:
                source.execute("PRAGMA busy_timeout = 0")
                source.backup(destination)
                backup_value_while_readers_pinned = _read_value(destination)
                backup_integrity_while_readers_pinned = _integrity_ok(destination)
            finally:
                destination.close()
                source.close()
            if backup_value_while_readers_pinned != 112:
                raise RuntimeError(
                    "online backup failed to capture latest committed source state: "
                    f"{backup_value_while_readers_pinned!r}"
                )
            if not backup_integrity_while_readers_pinned:
                raise RuntimeError("backup integrity_check failed with readers pinned")

            _read_snapshot(older_reader, 110)
            _read_snapshot(newer_reader, 111)
            checkpoint_busy_after_backup = _checkpoint_is_busy(database)
            if not checkpoint_busy_after_backup:
                raise RuntimeError("backup incorrectly released reader checkpoint state")

            _kill_reader(older_reader)
            _read_snapshot(newer_reader, 111)
            checkpoint_busy_after_older_release = _checkpoint_is_busy(database)
            if not checkpoint_busy_after_older_release:
                raise RuntimeError("checkpoint released while newer reader remained pinned")

            second_commit = _commit_value(database, 113)
            _read_snapshot(newer_reader, 111)
            observer = sqlite3.connect(database, isolation_level=None, timeout=0.0)
            backup_connection = sqlite3.connect(backup, isolation_level=None, timeout=0.0)
            try:
                observer.execute("PRAGMA busy_timeout = 0")
                source_after_second_commit = _read_value(observer)
                backup_after_source_commit = _read_value(backup_connection)
            finally:
                backup_connection.close()
                observer.close()
            if source_after_second_commit != 113 or backup_after_source_commit != 112:
                raise RuntimeError(
                    "source/backup independence mismatch after second commit: "
                    f"source={source_after_second_commit!r} backup={backup_after_source_commit!r}"
                )

            checkpoint_busy_after_second_commit = _checkpoint_is_busy(database)
            if not checkpoint_busy_after_second_commit:
                raise RuntimeError("checkpoint unexpectedly completed with newer reader pinned")

            _kill_reader(newer_reader)
            newer_reader = None
            checkpoint_busy_after_final_release = _checkpoint_is_busy(database)
            if checkpoint_busy_after_final_release:
                raise RuntimeError("checkpoint remained busy after final reader release")
        finally:
            if writer is not None and writer.poll() is None:
                _kill_writer(writer)
            if newer_reader is not None and newer_reader.poll() is None:
                _kill_reader(newer_reader)
            if older_reader.poll() is None:
                _kill_reader(older_reader)

        source_reopen = sqlite3.connect(database, isolation_level=None, timeout=0.0)
        backup_reopen = sqlite3.connect(backup, isolation_level=None, timeout=0.0)
        try:
            source_reopen.execute("PRAGMA busy_timeout = 0")
            backup_reopen.execute("PRAGMA busy_timeout = 0")
            source_reopen_value = _read_value(source_reopen)
            backup_reopen_value = _read_value(backup_reopen)
            source_integrity = _integrity_ok(source_reopen)
            backup_integrity = _integrity_ok(backup_reopen)
            _write_value(backup_reopen, 114)
            backup_after_backup_write = _read_value(backup_reopen)
            source_after_backup_write = _read_value(source_reopen)
        finally:
            backup_reopen.close()
            source_reopen.close()

        if (
            first_commit != 111
            or second_commit != 113
            or source_reopen_value != 113
            or backup_reopen_value != 112
            or not source_integrity
            or not backup_integrity
            or backup_after_backup_write != 114
            or source_after_backup_write != 113
        ):
            raise RuntimeError("multi-reader backup recovery mismatch")

        source_followup = _commit_value(database, 115)
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
            source_followup != 115
            or final_source_value != 115
            or final_backup_value != 114
            or not final_source_integrity
            or not final_backup_integrity
        ):
            raise RuntimeError("post-release multi-reader source/backup durability mismatch")

        payload = {
            "journal_mode": journal_mode,
            "older_reader_snapshot": 110,
            "first_writer_committed_value": first_commit,
            "newer_reader_snapshot": 111,
            "committed_writer_value": 112,
            "committed_writer_forced_crash": True,
            "older_reader_snapshot_after_writer_crash": 110,
            "newer_reader_snapshot_after_writer_crash": 111,
            "fresh_source_value_after_writer_crash": source_after_writer_crash,
            "checkpoint_busy_before_backup": checkpoint_busy_before_backup,
            "backup_value_while_readers_pinned": backup_value_while_readers_pinned,
            "backup_integrity_while_readers_pinned": "ok",
            "older_reader_snapshot_after_backup": 110,
            "newer_reader_snapshot_after_backup": 111,
            "checkpoint_busy_after_backup": checkpoint_busy_after_backup,
            "older_reader_forced_release": True,
            "newer_reader_snapshot_after_older_release": 111,
            "checkpoint_busy_after_older_release": checkpoint_busy_after_older_release,
            "second_writer_committed_value": second_commit,
            "newer_reader_snapshot_after_second_commit": 111,
            "fresh_source_value_after_second_commit": source_after_second_commit,
            "backup_value_after_source_commit": backup_after_source_commit,
            "checkpoint_busy_after_second_commit": checkpoint_busy_after_second_commit,
            "newer_reader_forced_release": True,
            "checkpoint_busy_after_final_release": checkpoint_busy_after_final_release,
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
            "protocol_error: WAL multi-reader backup target requires empty input",
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
