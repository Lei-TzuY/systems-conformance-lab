from __future__ import annotations

import json
import pathlib
import sqlite3
import subprocess
import sys
import tempfile

from ._sqlite_wal_multi_reader_crash_worker import _checkpoint_is_busy, _commit_value
from ._sqlite_wal_newer_reader_crash_worker import _start_reader
from ._sqlite_wal_reader_crash_worker import _kill_reader, _read_snapshot, _read_value


def _run() -> bytes:
    with tempfile.TemporaryDirectory(
        prefix="systems-conformance-wal-partial-reader-release-commit-"
    ) as directory:
        database = str(pathlib.Path(directory) / "target.sqlite")
        connection = sqlite3.connect(database, isolation_level=None)
        try:
            connection.execute("CREATE TABLE items(v INTEGER NOT NULL)")
            connection.execute("INSERT INTO items VALUES (40)")
            journal_mode = str(
                connection.execute("PRAGMA journal_mode = WAL").fetchone()[0]
            ).lower()
            if journal_mode != "wal":
                raise RuntimeError(f"WAL unavailable: {journal_mode!r}")
            connection.execute("PRAGMA wal_autocheckpoint = 0")
        finally:
            connection.close()

        older_reader = _start_reader(database, 40)
        newer_reader: subprocess.Popen[str] | None = None
        try:
            first_commit = _commit_value(database, 41)
            _read_snapshot(older_reader, 40)

            newer_reader = _start_reader(database, 41)
            second_commit = _commit_value(database, 42)
            _read_snapshot(newer_reader, 41)
            _read_snapshot(older_reader, 40)

            checkpoint_busy_before_release = _checkpoint_is_busy(database)
            if not checkpoint_busy_before_release:
                raise RuntimeError(
                    "truncating checkpoint unexpectedly completed with two pinned readers"
                )

            _kill_reader(newer_reader)
            newer_reader = None
            _read_snapshot(older_reader, 40)

            checkpoint_busy_after_newer_release = _checkpoint_is_busy(database)
            if not checkpoint_busy_after_newer_release:
                raise RuntimeError(
                    "newer reader release incorrectly removed older checkpoint constraint"
                )

            third_commit = _commit_value(database, 43)
            _read_snapshot(older_reader, 40)

            observer = sqlite3.connect(database, isolation_level=None, timeout=0.0)
            try:
                observer.execute("PRAGMA busy_timeout = 0")
                observer_value = _read_value(observer)
            finally:
                observer.close()
            if observer_value != 43:
                raise RuntimeError(
                    "fresh observer did not see commit made with older snapshot pinned: "
                    f"{observer_value!r}"
                )

            checkpoint_busy_after_commit = _checkpoint_is_busy(database)
            if not checkpoint_busy_after_commit:
                raise RuntimeError(
                    "committed writer incorrectly released older checkpoint constraint"
                )

            _kill_reader(older_reader)
            checkpoint_busy_after_final_release = _checkpoint_is_busy(database)
            if checkpoint_busy_after_final_release:
                raise RuntimeError(
                    "truncating checkpoint remained busy after final reader release"
                )
        finally:
            if newer_reader is not None and newer_reader.poll() is None:
                newer_reader.kill()
                newer_reader.communicate(timeout=2.0)
            if older_reader.poll() is None:
                older_reader.kill()
                older_reader.communicate(timeout=2.0)

        verified = sqlite3.connect(database, isolation_level=None, timeout=0.0)
        try:
            verified.execute("PRAGMA busy_timeout = 0")
            durable_value = _read_value(verified)
            integrity = verified.execute("PRAGMA integrity_check").fetchall() == [("ok",)]
            final_checkpoint_busy = _checkpoint_is_busy(database)
        finally:
            verified.close()

        if (
            first_commit != 41
            or second_commit != 42
            or third_commit != 43
            or durable_value != 43
            or not integrity
            or final_checkpoint_busy
        ):
            raise RuntimeError(
                "partial-reader-release commit recovery mismatch: "
                f"first_commit={first_commit!r} second_commit={second_commit!r} "
                f"third_commit={third_commit!r} durable={durable_value!r} "
                f"integrity={integrity!r} final_checkpoint_busy={final_checkpoint_busy!r}"
            )

        payload = {
            "journal_mode": journal_mode,
            "older_reader_snapshot": 40,
            "first_writer_committed_value": first_commit,
            "newer_reader_snapshot": 41,
            "second_writer_committed_value": second_commit,
            "checkpoint_busy_before_newer_reader_release": checkpoint_busy_before_release,
            "newer_reader_forced_release": True,
            "older_reader_snapshot_after_newer_release": 40,
            "checkpoint_busy_after_newer_reader_release": (
                checkpoint_busy_after_newer_release
            ),
            "third_writer_committed_value": third_commit,
            "older_reader_snapshot_after_third_commit": 40,
            "fresh_observer_value_while_older_reader_pinned": observer_value,
            "checkpoint_busy_after_third_commit": checkpoint_busy_after_commit,
            "older_reader_forced_release": True,
            "checkpoint_busy_after_final_reader_release": (
                checkpoint_busy_after_final_release
            ),
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
            "protocol_error: WAL partial-reader-release commit target requires empty input",
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
