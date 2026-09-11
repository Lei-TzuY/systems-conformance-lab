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


def _observer(database: str) -> int:
    connection = sqlite3.connect(database, isolation_level=None, timeout=0.0)
    try:
        connection.execute("PRAGMA busy_timeout = 0")
        print(_read_value(connection), flush=True)
    finally:
        connection.close()
    return 0


def _read_value_in_child(database: str) -> int:
    completed = subprocess.run(
        [sys.executable, "-m", _WORKER_MODULE, "--observer", database],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=2.0,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            "recovery observer failed: "
            f"exit={completed.returncode} stderr={completed.stderr.strip()!r}"
        )
    if completed.stderr.strip():
        raise RuntimeError(
            f"recovery observer emitted stderr: {completed.stderr.strip()!r}"
        )
    value = completed.stdout.strip()
    try:
        return int(value)
    except ValueError as exc:
        raise RuntimeError(f"invalid recovery observer value: {value!r}") from exc


def _checkpoint(connection: sqlite3.Connection) -> tuple[int, int, int]:
    row = connection.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
    if row is None or len(row) != 3:
        raise RuntimeError(f"unexpected wal_checkpoint result: {row!r}")
    return int(row[0]), int(row[1]), int(row[2])


def _checkpoint_worker(database: str) -> int:
    connection = sqlite3.connect(database, isolation_level=None, timeout=0.0)
    try:
        connection.execute("PRAGMA busy_timeout = 0")
        busy, _, _ = _checkpoint(connection)
        print(busy, flush=True)
    finally:
        connection.close()
    return 0


def _run_checkpoint_in_child(database: str) -> int:
    completed = subprocess.run(
        [sys.executable, "-m", _WORKER_MODULE, "--checkpoint", database],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=2.0,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            "checkpoint worker failed: "
            f"exit={completed.returncode} stderr={completed.stderr.strip()!r}"
        )
    if completed.stderr.strip():
        raise RuntimeError(
            f"checkpoint worker emitted stderr: {completed.stderr.strip()!r}"
        )
    value = completed.stdout.strip()
    if value not in {"0", "1"}:
        raise RuntimeError(f"invalid checkpoint worker busy result: {value!r}")
    return int(value)


def _integrity_worker(database: str) -> int:
    connection = sqlite3.connect(database, isolation_level=None, timeout=0.0)
    try:
        connection.execute("PRAGMA busy_timeout = 0")
        rows = connection.execute("PRAGMA integrity_check").fetchall()
        if rows != [("ok",)]:
            raise RuntimeError(f"integrity_check failed: {rows!r}")
        print("ok", flush=True)
    finally:
        connection.close()
    return 0


def _run_integrity_check_in_child(database: str) -> str:
    completed = subprocess.run(
        [sys.executable, "-m", _WORKER_MODULE, "--integrity-check", database],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=2.0,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            "integrity worker failed: "
            f"exit={completed.returncode} stderr={completed.stderr.strip()!r}"
        )
    if completed.stderr.strip():
        raise RuntimeError(
            f"integrity worker emitted stderr: {completed.stderr.strip()!r}"
        )
    value = completed.stdout.strip()
    if value != "ok":
        raise RuntimeError(f"invalid integrity worker result: {value!r}")
    return value


def _run(
    *,
    commit_before_crash: bool,
    pin_reader_snapshot: bool,
    checkpoint_after_crash: bool,
    checkpoint_in_child: bool,
    recover_in_child: bool,
    integrity_check_in_child: bool,
) -> bytes:
    if checkpoint_after_crash and not (commit_before_crash and pin_reader_snapshot):
        raise RuntimeError(
            "checkpoint-after-crash requires committed writer and pinned reader"
        )
    if checkpoint_in_child and not checkpoint_after_crash:
        raise RuntimeError("checkpoint-in-child requires checkpoint-after-crash")
    if integrity_check_in_child and not checkpoint_after_crash:
        raise RuntimeError("integrity-check-in-child requires checkpoint-after-crash")

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

        expected_recovered_value = 1 if commit_before_crash else 0
        observer_recovered_value: int | None = None
        if recover_in_child:
            observer_recovered_value = _read_value_in_child(database)
            if observer_recovered_value != expected_recovered_value:
                state = "committed" if commit_before_crash else "uncommitted"
                raise RuntimeError(
                    f"{state} child observer recovery mismatch: {observer_recovered_value!r}"
                )

        recovered = sqlite3.connect(database, isolation_level=None, timeout=0.0)
        try:
            recovered.execute("PRAGMA busy_timeout = 0")
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
            integrity_check: str | None = None
            if checkpoint_after_crash:
                if checkpoint_in_child:
                    blocked_busy = _run_checkpoint_in_child(database)
                    blocked_details: object = blocked_busy
                else:
                    blocked_busy, blocked_log, blocked_checkpointed = _checkpoint(recovered)
                    blocked_details = (blocked_busy, blocked_log, blocked_checkpointed)
                if blocked_busy != 1:
                    raise RuntimeError(
                        "TRUNCATE checkpoint unexpectedly completed while pre-crash reader "
                        f"snapshot was pinned: {blocked_details!r}"
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
                    if checkpoint_in_child:
                        released_busy = _run_checkpoint_in_child(database)
                        released_details: object = released_busy
                    else:
                        released_busy, released_log, released_checkpointed = _checkpoint(recovered)
                        released_details = (released_busy, released_log, released_checkpointed)
                    if released_busy != 0:
                        raise RuntimeError(
                            "TRUNCATE checkpoint remained busy after pre-crash reader release: "
                            f"{released_details!r}"
                        )
                    released_checkpoint_busy = False

                post_release_value = _read_value(recovered)
                if post_release_value != 2:
                    raise RuntimeError(
                        f"fresh state after reader release mismatch: {post_release_value!r}"
                    )
                if integrity_check_in_child:
                    integrity_check = _run_integrity_check_in_child(database)
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
        if recover_in_child:
            payload["observer_recovered_value"] = observer_recovered_value
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
        if checkpoint_in_child:
            payload["checkpoint_process"] = "child"
        if integrity_check_in_child:
            payload.update(
                {
                    "integrity_check": integrity_check,
                    "integrity_process": "child",
                }
            )
        return (json.dumps(payload, separators=(",", ":")) + "\n").encode()


def main() -> int:
    if len(sys.argv) == 3 and sys.argv[1] in {"--writer-uncommitted", "--writer-committed"}:
        return _writer(sys.argv[2], commit_before_crash=sys.argv[1] == "--writer-committed")
    if len(sys.argv) == 3 and sys.argv[1] == "--observer":
        return _observer(sys.argv[2])
    if len(sys.argv) == 3 and sys.argv[1] == "--checkpoint":
        return _checkpoint_worker(sys.argv[2])
    if len(sys.argv) == 3 and sys.argv[1] == "--integrity-check":
        return _integrity_worker(sys.argv[2])

    commit_before_crash = "--commit-before-crash" in sys.argv[1:]
    pin_reader_snapshot = "--pin-reader-snapshot" in sys.argv[1:]
    checkpoint_after_crash = "--checkpoint-after-crash" in sys.argv[1:]
    checkpoint_in_child = "--checkpoint-in-child" in sys.argv[1:]
    recover_in_child = "--recover-in-child" in sys.argv[1:]
    integrity_check_in_child = "--integrity-check-in-child" in sys.argv[1:]
    expected_arguments = set()
    if commit_before_crash:
        expected_arguments.add("--commit-before-crash")
    if pin_reader_snapshot:
        expected_arguments.add("--pin-reader-snapshot")
    if checkpoint_after_crash:
        expected_arguments.add("--checkpoint-after-crash")
    if checkpoint_in_child:
        expected_arguments.add("--checkpoint-in-child")
    if recover_in_child:
        expected_arguments.add("--recover-in-child")
    if integrity_check_in_child:
        expected_arguments.add("--integrity-check-in-child")
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
                checkpoint_in_child=checkpoint_in_child,
                recover_in_child=recover_in_child,
                integrity_check_in_child=integrity_check_in_child,
            )
        )
    except (OSError, RuntimeError, sqlite3.Error, subprocess.SubprocessError) as exc:
        print(f"target_error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())