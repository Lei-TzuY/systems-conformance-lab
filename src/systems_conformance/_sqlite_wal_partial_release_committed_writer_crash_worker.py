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


def _committed_writer_main(database: str, value: int) -> int:
    connection = sqlite3.connect(database, isolation_level=None, timeout=0.0)
    try:
        connection.execute("PRAGMA busy_timeout = 0")
        connection.execute("BEGIN IMMEDIATE")
        connection.execute("UPDATE items SET v = ?", (value,))
        connection.execute("COMMIT")
        print(f"COMMITTED {value}", flush=True)
        sys.stdin.read()
    finally:
        connection.close()
    return 0


def _start_committed_writer(database: str, value: int) -> subprocess.Popen[str]:
    writer = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "systems_conformance._sqlite_wal_partial_release_committed_writer_crash_worker",
            "--committed-writer",
            database,
            str(value),
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        shell=False,
    )
    assert writer.stdout is not None
    ready = writer.stdout.readline().strip()
    if ready != f"COMMITTED {value}":
        stderr = ""
        if writer.stderr is not None:
            stderr = writer.stderr.read()
        writer.kill()
        writer.communicate(timeout=2.0)
        raise RuntimeError(f"committed writer failed to become ready: {ready!r} {stderr!r}")
    return writer


def _kill_writer(writer: subprocess.Popen[str]) -> None:
    writer.kill()
    writer.communicate(timeout=2.0)


def _run() -> bytes:
    with tempfile.TemporaryDirectory(
        prefix="systems-conformance-wal-partial-release-committed-writer-crash-"
    ) as directory:
        database = str(pathlib.Path(directory) / "target.sqlite")
        connection = sqlite3.connect(database, isolation_level=None)
        try:
            connection.execute("CREATE TABLE items(v INTEGER NOT NULL)")
            connection.execute("INSERT INTO items VALUES (60)")
            journal_mode = str(
                connection.execute("PRAGMA journal_mode = WAL").fetchone()[0]
            ).lower()
            if journal_mode != "wal":
                raise RuntimeError(f"WAL unavailable: {journal_mode!r}")
            connection.execute("PRAGMA wal_autocheckpoint = 0")
        finally:
            connection.close()

        older_reader = _start_reader(database, 60)
        newer_reader: subprocess.Popen[str] | None = None
        writer: subprocess.Popen[str] | None = None
        try:
            first_commit = _commit_value(database, 61)
            _read_snapshot(older_reader, 60)

            newer_reader = _start_reader(database, 61)
            second_commit = _commit_value(database, 62)
            _read_snapshot(newer_reader, 61)
            _read_snapshot(older_reader, 60)

            checkpoint_busy_before_release = _checkpoint_is_busy(database)
            if not checkpoint_busy_before_release:
                raise RuntimeError(
                    "truncating checkpoint unexpectedly completed with two pinned readers"
                )

            _kill_reader(newer_reader)
            newer_reader = None
            _read_snapshot(older_reader, 60)

            checkpoint_busy_after_newer_release = _checkpoint_is_busy(database)
            if not checkpoint_busy_after_newer_release:
                raise RuntimeError(
                    "newer reader release incorrectly removed older checkpoint constraint"
                )

            writer = _start_committed_writer(database, 63)
            _read_snapshot(older_reader, 60)
            _kill_writer(writer)
            writer = None

            _read_snapshot(older_reader, 60)
            observer = sqlite3.connect(database, isolation_level=None, timeout=0.0)
            try:
                observer.execute("PRAGMA busy_timeout = 0")
                observer_value_after_writer_crash = _read_value(observer)
            finally:
                observer.close()
            if observer_value_after_writer_crash != 63:
                raise RuntimeError(
                    "committed writer value was lost after process crash: "
                    f"{observer_value_after_writer_crash!r}"
                )

            checkpoint_busy_after_writer_crash = _checkpoint_is_busy(database)
            if not checkpoint_busy_after_writer_crash:
                raise RuntimeError(
                    "committed writer crash incorrectly released surviving reader checkpoint state"
                )

            _kill_reader(older_reader)
            checkpoint_busy_after_final_reader_release = _checkpoint_is_busy(database)
            if checkpoint_busy_after_final_reader_release:
                raise RuntimeError(
                    "truncating checkpoint remained busy after final reader release"
                )
        finally:
            if writer is not None and writer.poll() is None:
                _kill_writer(writer)
            if newer_reader is not None and newer_reader.poll() is None:
                _kill_reader(newer_reader)
            if older_reader.poll() is None:
                _kill_reader(older_reader)

        verified = sqlite3.connect(database, isolation_level=None, timeout=0.0)
        try:
            verified.execute("PRAGMA busy_timeout = 0")
            durable_value_before_followup = _read_value(verified)
            integrity_before_followup = verified.execute("PRAGMA integrity_check").fetchall() == [
                ("ok",)
            ]
        finally:
            verified.close()

        post_crash_write = _commit_value(database, 64)
        reopened = sqlite3.connect(database, isolation_level=None, timeout=0.0)
        try:
            reopened.execute("PRAGMA busy_timeout = 0")
            durable_value = _read_value(reopened)
            integrity = reopened.execute("PRAGMA integrity_check").fetchall() == [("ok",)]
            final_checkpoint_busy = _checkpoint_is_busy(database)
        finally:
            reopened.close()

        if (
            first_commit != 61
            or second_commit != 62
            or durable_value_before_followup != 63
            or not integrity_before_followup
            or post_crash_write != 64
            or durable_value != 64
            or not integrity
            or final_checkpoint_busy
        ):
            raise RuntimeError(
                "partial-release committed-writer crash recovery mismatch: "
                f"first_commit={first_commit!r} second_commit={second_commit!r} "
                f"durable_before_followup={durable_value_before_followup!r} "
                f"integrity_before_followup={integrity_before_followup!r} "
                f"post_crash_write={post_crash_write!r} durable={durable_value!r} "
                f"integrity={integrity!r} final_checkpoint_busy={final_checkpoint_busy!r}"
            )

        payload = {
            "journal_mode": journal_mode,
            "older_reader_snapshot": 60,
            "first_writer_committed_value": first_commit,
            "newer_reader_snapshot": 61,
            "second_writer_committed_value": second_commit,
            "checkpoint_busy_before_partial_release": checkpoint_busy_before_release,
            "newer_reader_forced_release": True,
            "checkpoint_busy_after_newer_release": checkpoint_busy_after_newer_release,
            "committed_writer_value": 63,
            "writer_forced_crash_after_commit": True,
            "older_reader_snapshot_after_writer_crash": 60,
            "fresh_observer_value_after_writer_crash": observer_value_after_writer_crash,
            "checkpoint_busy_after_writer_crash": checkpoint_busy_after_writer_crash,
            "older_reader_forced_release": True,
            "checkpoint_busy_after_final_reader_release": (
                checkpoint_busy_after_final_reader_release
            ),
            "durable_value_before_followup": durable_value_before_followup,
            "integrity_before_followup": "ok",
            "post_crash_write_value": post_crash_write,
            "fresh_reopen_value": durable_value,
            "fresh_reopen_integrity": "ok",
            "fresh_reopen_checkpoint_busy": final_checkpoint_busy,
        }
        return (json.dumps(payload, separators=(",", ":")) + "\n").encode()


def main() -> int:
    if len(sys.argv) == 4 and sys.argv[1] == "--committed-writer":
        try:
            return _committed_writer_main(sys.argv[2], int(sys.argv[3]))
        except (OSError, RuntimeError, ValueError, sqlite3.Error) as exc:
            print(f"writer_error: {exc}", file=sys.stderr)
            return 1

    if len(sys.argv) != 1:
        print("protocol_error: unexpected arguments", file=sys.stderr)
        return 2
    if sys.stdin.buffer.read(1):
        print(
            "protocol_error: WAL partial-release committed-writer crash target requires empty input",
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
