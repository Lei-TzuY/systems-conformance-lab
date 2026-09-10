from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
from pathlib import Path


def _checkpoint(connection: sqlite3.Connection) -> tuple[int, int, int]:
    row = connection.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
    if row is None or len(row) != 3:
        raise RuntimeError(f"unexpected wal_checkpoint result: {row!r}")
    return int(row[0]), int(row[1]), int(row[2])


def _run() -> bytes:
    with tempfile.TemporaryDirectory(
        prefix="systems-conformance-sqlite-wal-checkpoint-"
    ) as directory:
        database = str(Path(directory) / "case.sqlite")
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

        reader = sqlite3.connect(database, isolation_level=None, timeout=0.0)
        writer = sqlite3.connect(database, isolation_level=None, timeout=0.0)
        checkpoint = sqlite3.connect(database, isolation_level=None, timeout=0.0)
        try:
            for connection in (reader, writer, checkpoint):
                connection.execute("PRAGMA busy_timeout = 0")
            writer.execute("PRAGMA wal_autocheckpoint = 0")

            reader.execute("BEGIN")
            row = reader.execute("SELECT v FROM items").fetchone()
            if row is None or int(row[0]) != 0:
                raise RuntimeError(f"reader initial snapshot mismatch: {row!r}")

            for value in (1, 2, 3):
                writer.execute("BEGIN IMMEDIATE")
                writer.execute("UPDATE items SET v = ?", (value,))
                writer.commit()

            blocked_busy, blocked_log, blocked_checkpointed = _checkpoint(checkpoint)
            if blocked_busy != 1:
                raise RuntimeError(
                    "TRUNCATE checkpoint unexpectedly completed while reader snapshot "
                    f"was pinned: {(blocked_busy, blocked_log, blocked_checkpointed)!r}"
                )

            retained = reader.execute("SELECT v FROM items").fetchone()
            if retained is None or int(retained[0]) != 0:
                raise RuntimeError(f"reader snapshot changed during checkpoint: {retained!r}")
            reader.rollback()

            released_busy, released_log, released_checkpointed = _checkpoint(checkpoint)
            if released_busy != 0:
                raise RuntimeError(
                    "TRUNCATE checkpoint remained busy after reader release: "
                    f"{(released_busy, released_log, released_checkpointed)!r}"
                )

            fresh = reader.execute("SELECT v FROM items").fetchone()
            if fresh is None or int(fresh[0]) != 3:
                raise RuntimeError(f"fresh read mismatch after checkpoint: {fresh!r}")

            payload = {
                "journal_mode": "wal",
                "reader_snapshot": 0,
                "writer_committed_value": 3,
                "blocked_checkpoint": {
                    "busy": blocked_busy,
                    "log_frames": blocked_log,
                    "checkpointed_frames": blocked_checkpointed,
                },
                "released_checkpoint": {
                    "busy": released_busy,
                    "log_frames": released_log,
                    "checkpointed_frames": released_checkpointed,
                },
                "fresh_value": 3,
            }
            return (json.dumps(payload, separators=(",", ":")) + "\n").encode()
        finally:
            if reader.in_transaction:
                reader.rollback()
            if writer.in_transaction:
                writer.rollback()
            reader.close()
            writer.close()
            checkpoint.close()


def main() -> int:
    if sys.stdin.buffer.read():
        sys.stderr.write(
            "protocol_error: SQLite WAL checkpoint target requires empty input\n"
        )
        return 2
    try:
        output = _run()
    except (sqlite3.Error, RuntimeError) as exc:
        sys.stderr.write(f"sqlite_wal_checkpoint_error: {exc}\n")
        return 1
    sys.stdout.buffer.write(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
