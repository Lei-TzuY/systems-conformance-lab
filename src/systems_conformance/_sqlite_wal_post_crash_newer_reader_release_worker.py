from __future__ import annotations

import json
import pathlib
import sqlite3
import subprocess
import sys
import tempfile

from ._sqlite_wal_multi_reader_crash_worker import _checkpoint_is_busy, _commit_value
from ._sqlite_wal_newer_reader_crash_worker import _start_reader
from ._sqlite_wal_partial_release_committed_writer_crash_worker import (
    _kill_writer,
    _start_committed_writer,
)
from ._sqlite_wal_reader_crash_worker import _kill_reader, _read_snapshot, _read_value


def _run() -> bytes:
    with tempfile.TemporaryDirectory(prefix="systems-conformance-wal-post-crash-newer-release-") as directory:
        database = str(pathlib.Path(directory) / "target.sqlite")
        connection = sqlite3.connect(database, isolation_level=None)
        try:
            connection.execute("CREATE TABLE items(v INTEGER NOT NULL)")
            connection.execute("INSERT INTO items VALUES (80)")
            journal_mode = str(connection.execute("PRAGMA journal_mode = WAL").fetchone()[0]).lower()
            if journal_mode != "wal":
                raise RuntimeError(f"WAL unavailable: {journal_mode!r}")
            connection.execute("PRAGMA wal_autocheckpoint = 0")
        finally:
            connection.close()

        older_reader = _start_reader(database, 80)
        post_crash_reader: subprocess.Popen[str] | None = None
        writer: subprocess.Popen[str] | None = None
        try:
            first_commit = _commit_value(database, 81)
            _read_snapshot(older_reader, 80)

            writer = _start_committed_writer(database, 82)
            _kill_writer(writer)
            writer = None

            _read_snapshot(older_reader, 80)
            observer = sqlite3.connect(database, isolation_level=None, timeout=0.0)
            try:
                observer.execute("PRAGMA busy_timeout = 0")
                committed_value_after_crash = _read_value(observer)
            finally:
                observer.close()
            if committed_value_after_crash != 82:
                raise RuntimeError(f"committed value lost after writer crash: {committed_value_after_crash!r}")

            post_crash_reader = _start_reader(database, 82)
            _read_snapshot(post_crash_reader, 82)
            second_commit = _commit_value(database, 83)
            _read_snapshot(older_reader, 80)
            _read_snapshot(post_crash_reader, 82)
            checkpoint_busy_with_two_readers = _checkpoint_is_busy(database)
            if not checkpoint_busy_with_two_readers:
                raise RuntimeError("checkpoint unexpectedly completed with two pinned readers")

            _kill_reader(post_crash_reader)
            post_crash_reader = None
            _read_snapshot(older_reader, 80)
            checkpoint_busy_after_newer_release = _checkpoint_is_busy(database)
            if not checkpoint_busy_after_newer_release:
                raise RuntimeError("newer reader release incorrectly removed older reader state")

            observer = sqlite3.connect(database, isolation_level=None, timeout=0.0)
            try:
                observer.execute("PRAGMA busy_timeout = 0")
                fresh_value_after_newer_release = _read_value(observer)
            finally:
                observer.close()
            if fresh_value_after_newer_release != 83:
                raise RuntimeError(f"fresh observer missed latest commit: {fresh_value_after_newer_release!r}")

            third_commit = _commit_value(database, 84)
            _read_snapshot(older_reader, 80)
            checkpoint_busy_after_third_commit = _checkpoint_is_busy(database)
            if not checkpoint_busy_after_third_commit:
                raise RuntimeError("checkpoint unexpectedly completed with older reader still pinned")

            observer = sqlite3.connect(database, isolation_level=None, timeout=0.0)
            try:
                observer.execute("PRAGMA busy_timeout = 0")
                fresh_value_while_older_pinned = _read_value(observer)
            finally:
                observer.close()
            if fresh_value_while_older_pinned != 84:
                raise RuntimeError(f"fresh observer missed third commit: {fresh_value_while_older_pinned!r}")

            _kill_reader(older_reader)
            checkpoint_busy_after_final_release = _checkpoint_is_busy(database)
            if checkpoint_busy_after_final_release:
                raise RuntimeError("checkpoint remained busy after final reader release")
        finally:
            if writer is not None and writer.poll() is None:
                _kill_writer(writer)
            if post_crash_reader is not None and post_crash_reader.poll() is None:
                _kill_reader(post_crash_reader)
            if older_reader.poll() is None:
                _kill_reader(older_reader)

        reopened = sqlite3.connect(database, isolation_level=None, timeout=0.0)
        try:
            reopened.execute("PRAGMA busy_timeout = 0")
            durable_before_followup = _read_value(reopened)
            integrity_before_followup = reopened.execute("PRAGMA integrity_check").fetchall() == [("ok",)]
        finally:
            reopened.close()

        followup_commit = _commit_value(database, 85)
        verified = sqlite3.connect(database, isolation_level=None, timeout=0.0)
        try:
            verified.execute("PRAGMA busy_timeout = 0")
            durable_value = _read_value(verified)
            integrity = verified.execute("PRAGMA integrity_check").fetchall() == [("ok",)]
            final_checkpoint_busy = _checkpoint_is_busy(database)
        finally:
            verified.close()

        if (
            first_commit != 81
            or second_commit != 83
            or third_commit != 84
            or durable_before_followup != 84
            or not integrity_before_followup
            or followup_commit != 85
            or durable_value != 85
            or not integrity
            or final_checkpoint_busy
        ):
            raise RuntimeError("post-crash newer-reader release recovery mismatch")

        payload = {
            "journal_mode": journal_mode,
            "older_reader_snapshot": 80,
            "first_writer_committed_value": first_commit,
            "committed_writer_value": 82,
            "committed_writer_forced_crash": True,
            "fresh_observer_value_after_writer_crash": committed_value_after_crash,
            "post_crash_reader_snapshot": 82,
            "second_writer_committed_value": second_commit,
            "checkpoint_busy_with_two_readers": checkpoint_busy_with_two_readers,
            "post_crash_reader_forced_release": True,
            "older_reader_snapshot_after_newer_release": 80,
            "checkpoint_busy_after_newer_release": checkpoint_busy_after_newer_release,
            "fresh_observer_value_after_newer_release": fresh_value_after_newer_release,
            "third_writer_committed_value": third_commit,
            "older_reader_snapshot_after_third_commit": 80,
            "checkpoint_busy_after_third_commit": checkpoint_busy_after_third_commit,
            "fresh_observer_value_while_older_pinned": fresh_value_while_older_pinned,
            "older_reader_forced_release": True,
            "checkpoint_busy_after_final_release": checkpoint_busy_after_final_release,
            "durable_value_before_followup": durable_before_followup,
            "integrity_before_followup": "ok",
            "followup_commit_value": followup_commit,
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
        print("protocol_error: WAL post-crash newer-reader release target requires empty input", file=sys.stderr)
        return 2
    try:
        sys.stdout.buffer.write(_run())
    except (OSError, RuntimeError, sqlite3.Error, subprocess.SubprocessError) as exc:
        print(f"target_error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
