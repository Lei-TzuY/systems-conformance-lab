from __future__ import annotations

import json
import pathlib
import sqlite3
import subprocess
import sys
import tempfile
import time

_WORKER_MODULE = "systems_conformance._sqlite_wal_crash_recovery_worker"


def _writer(database: str, *, commit_before_crash: bool) -> int:
    connection = sqlite3.connect(database, isolation_level=None, timeout=0.0)
    try:
        connection.execute("PRAGMA busy_timeout = 0")
        connection.execute("BEGIN IMMEDIATE")
        connection.execute("UPDATE items SET v = 1")
        if commit_before_crash:
            connection.commit()
            marker = "COMMITTED_READY"
        else:
            marker = "UNCOMMITTED_READY"
        print(marker, flush=True)
        while True:
            time.sleep(60.0)
    finally:
        connection.close()


def _read_value(connection: sqlite3.Connection) -> int:
    row = connection.execute("SELECT v FROM items").fetchone()
    if row is None:
        raise RuntimeError("items row missing")
    return int(row[0])


def _checkpoint(connection: sqlite3.Connection) -> tuple[int, int, int]:
    row = connection.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
    if row is None or len(row) != 3:
        raise RuntimeError(f"unexpected wal_checkpoint result: {row!r}")
    return int(row[0]), int(row[1]), int(row[2])


def _run(
    *,
    commit_before_crash: bool,
    pin_reader_snapshot: bool,
    checkpoint_after_crash: bool,
) -> bytes:
    if checkpoint_after_crash and not (commit_before_crash and pin_reader_snapshot):
        raise RuntimeError(
            "checkpoint-after-crash requires committed writer and pinned reader"
        )

    with tempfile.TemporaryDirectory(
        prefix="systems-conformance-sqlite-wal-crash-recovery-"
    ) as directory:
        database = str(pathlib.Path(directory) / "case.sqlite")
        bootstrap = sqlite3.connect(database, isolation_level=None)
        try:
            row = bootstrap.execute("PRAGMA journal_mode = WAL").fetchone()
            actual = None if row is None else str(row[0]).lower()
            if actual != "wal":
                raise RuntimeError(f"SQLite WAL unavailable: got {actual}")
            bootstrap.execute("PRAGMA wal_autocheckpoint = 0")
            bootstrap.execute("CREATE TABLE items(v INTEGER NOT NULL)")
            bootstrap.execute("INSERT INTO items VALUES (0)")
        finally:
            bootstrap.close()

        pinned_reader: sqlite3.Connection | None = None
        pinned_reader_value: int | None = None
        if pin_reader_snapshot:
            pinned_reader = sqlite3.connect(database, isolation_level=None, timeout=0.0)
            pinned_reader.execute("PRAGMA busy_timeout = 0")
            pinned_reader.execute("BEGIN")
            pinned_reader_value = _read_value(pinned_reader)
            if pinned_reader_value != 0:
                raise RuntimeError(
                    f"reader failed to pin initial snapshot: {pinned_reader_value!r}"
                )

        writer_mode = "--writer-committed" if commit_before_crash else "--writer-uncommitted"
        expected_marker = "COMMITTED_READY" if commit_before_crash else "UNCOMMITTED_READY"
        process = subprocess.Popen(
            [sys.executable, "-m", _WORKER_MODULE, writer_mode, database],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            if process.stdout is None:
                raise RuntimeError("writer stdout pipe unavailable")
            marker = process.stdout.readline().strip()
            if marker != expected_marker:
                stderr = ""
                if process.stderr is not None:
                    stderr = process.stderr.read().strip()
                raise RuntimeError(
                    "writer failed before crash checkpoint: "
                    f"marker={marker!r} stderr={stderr!r}"
                )
            process.kill()
            _, stderr = process.communicate(timeout=2.0)
            if process.returncode == 0:
                raise RuntimeError("writer unexpectedly exited successfully after forced kill")
            if stderr.strip():
                raise RuntimeError(
                    f"writer emitted stderr before forced kill: {stderr.strip()!r}"
                )
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate(timeout=2.0)

        recovered = sqlite3.connect(database, isolation_level=None, timeout=0.0)
        try:
            recovered.execute("PRAGMA busy_timeout = 0")
            expected_recovered_value = 1 if commit_before_crash else 0
            recovered_value = _read_value(recovered)
            if recovered_value != expected_recovered_value:
                state = "committed" if commit_before_crash else "uncommitted"
                raise RuntimeError(
                    f"{state} writer recovery mismatch: {recovered_value!r}"
                )

            if pinned_reader is not None:
                snapshot_after_crash = _read_value(pinned_reader)
                if snapshot_after_crash != 0:
                    raise RuntimeError(
                        "pinned reader snapshot changed after writer crash: "
                        f"{snapshot_after_crash!r}"
                    )

            blocked_checkpoint_busy: bool | None = None
            released_checkpoint_busy: bool | None = None
            if checkpoint_after_crash:
                blocked_busy, blocked_log, blocked_checkpointed = _checkpoint(recovered)
                if blocked_busy != 1:
                    raise RuntimeError(
                        "TRUNCATE checkpoint unexpectedly completed while pre-crash reader "
                        "snapshot was pinned: "
                        f"{(blocked_busy, blocked_log, blocked_checkpointed)!r}"
                    )
                blocked_checkpoint_busy = True

            recovered.execute("BEGIN IMMEDIATE")
            recovered.execute("UPDATE items SET v = 2")
            recovered.commit()
            fresh_committed_value = _read_value(recovered)
            if fresh_committed_value != 2:
                raise RuntimeError(
                    f"fresh commit after recovery mismatch: {fresh_committed_value!r}"
                )

            if pinned_reader is not None:
                snapshot_after_fresh_commit = _read_value(pinned_reader)
                if snapshot_after_fresh_commit != 0:
                    raise RuntimeError(
                        "pinned reader snapshot changed after fresh commit: "
                        f"{snapshot_after_fresh_commit!r}"
                    )
                pinned_reader.rollback()
                pinned_reader.close()
                pinned_reader = None

                if checkpoint_after_crash:
                    released_busy, released_log, released_checkpointed = _checkpoint(recovered)
                    if released_busy != 0:
                        raise RuntimeError(
                            "TRUNCATE checkpoint remained busy after pre-crash reader release: "
                            f"{(released_busy, released_log, released_checkpointed)!r}"
                        )
                    released_checkpoint_busy = False

                post_release_value = _read_value(recovered)
                if post_release_value != 2:
                    raise RuntimeError(
                        f"fresh state after reader release mismatch: {post_release_value!r}"
                    )
            else:
                post_release_value = None
        finally:
            recovered.close()
            if pinned_reader is not None:
                pinned_reader.rollback()
                pinned_reader.close()

        payload = {
            "journal_mode": "wal",
            "writer_checkpoint": (
                "committed_update_ready" if commit_before_crash else "uncommitted_update_ready"
            ),
            "writer_terminated": True,
            "recovered_value": recovered_value,
            "fresh_committed_value": fresh_committed_value,
        }
        if pin_reader_snapshot:
            payload.update(
                {
                    "reader_snapshot_pinned": True,
                    "pinned_reader_value": pinned_reader_value,
                    "post_release_value": post_release_value,
                }
            )
        if checkpoint_after_crash:
            payload.update(
                {
                    "blocked_checkpoint_busy": blocked_checkpoint_busy,
                    "released_checkpoint_busy": released_checkpoint_busy,
                }
            )
        return (json.dumps(payload, separators=(",", ":")) + "\n").encode()


def main() -> int:
    if len(sys.argv) == 3 and sys.argv[1] in {"--writer-uncommitted", "--writer-committed"}:
        return _writer(sys.argv[2], commit_before_crash=sys.argv[1] == "--writer-committed")

    commit_before_crash = "--commit-before-crash" in sys.argv[1:]
    pin_reader_snapshot = "--pin-reader-snapshot" in sys.argv[1:]
    checkpoint_after_crash = "--checkpoint-after-crash" in sys.argv[1:]
    expected_arguments = set()
    if commit_before_crash:
        expected_arguments.add("--commit-before-crash")
    if pin_reader_snapshot:
        expected_arguments.add("--pin-reader-snapshot")
    if checkpoint_after_crash:
        expected_arguments.add("--checkpoint-after-crash")
    if len(sys.argv[1:]) != len(expected_arguments) or set(sys.argv[1:]) != expected_arguments:
        print("protocol_error: unexpected arguments", file=sys.stderr)
        return 2

    if sys.stdin.buffer.read(1):
        print(
            "protocol_error: SQLite WAL crash recovery target requires empty input",
            file=sys.stderr,
        )
        return 2
    try:
        sys.stdout.buffer.write(
            _run(
                commit_before_crash=commit_before_crash,
                pin_reader_snapshot=pin_reader_snapshot,
                checkpoint_after_crash=checkpoint_after_crash,
            )
        )
    except (OSError, RuntimeError, sqlite3.Error, subprocess.SubprocessError) as exc:
        print(f"target_error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
