from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
from pathlib import Path

_EXPECTED_BUSY_SNAPSHOT = sqlite3.SQLITE_BUSY_SNAPSHOT


def _read_value(connection: sqlite3.Connection) -> int:
    row = connection.execute("SELECT v FROM items").fetchone()
    if row is None:
        raise RuntimeError("reader observed no row")
    return int(row[0])


def _run() -> bytes:
    with tempfile.TemporaryDirectory(
        prefix="systems-conformance-sqlite-wal-busy-snapshot-"
    ) as directory:
        database = str(Path(directory) / "case.sqlite")
        bootstrap = sqlite3.connect(database, isolation_level=None)
        try:
            row = bootstrap.execute("PRAGMA journal_mode = WAL").fetchone()
            actual = None if row is None else str(row[0]).lower()
            if actual != "wal":
                raise RuntimeError(f"SQLite WAL unavailable: got {actual}")
            bootstrap.execute("CREATE TABLE items(v INTEGER NOT NULL)")
            bootstrap.execute("INSERT INTO items VALUES (0)")
        finally:
            bootstrap.close()

        reader = sqlite3.connect(database, isolation_level=None, timeout=0.0)
        writer = sqlite3.connect(database, isolation_level=None, timeout=0.0)
        try:
            reader.execute("PRAGMA busy_timeout = 0")
            writer.execute("PRAGMA busy_timeout = 0")

            reader.execute("BEGIN")
            initial_value = _read_value(reader)
            if initial_value != 0:
                raise RuntimeError(f"reader initial snapshot mismatch: {initial_value}")

            writer.execute("BEGIN IMMEDIATE")
            writer.execute("UPDATE items SET v = 1")
            writer.commit()

            try:
                reader.execute("UPDATE items SET v = 2")
            except sqlite3.OperationalError as exc:
                error_code = exc.sqlite_errorcode
                if error_code != _EXPECTED_BUSY_SNAPSHOT:
                    raise RuntimeError(
                        "stale reader upgrade produced unexpected SQLite error "
                        f"code: {error_code}"
                    ) from exc
            else:
                raise RuntimeError("stale WAL reader unexpectedly upgraded to writer")

            retained_value = _read_value(reader)
            if retained_value != 0:
                raise RuntimeError(
                    "stale reader snapshot changed after failed upgrade: "
                    f"{retained_value}"
                )
            reader.rollback()

            refreshed_value = _read_value(reader)
            if refreshed_value != 1:
                raise RuntimeError(
                    "fresh read mismatch after stale reader rollback: "
                    f"{refreshed_value}"
                )

            payload = {
                "journal_mode": "wal",
                "initial_value": initial_value,
                "writer_committed_value": 1,
                "upgrade_error_code": _EXPECTED_BUSY_SNAPSHOT,
                "retained_value": retained_value,
                "refreshed_value": refreshed_value,
            }
            return (json.dumps(payload, separators=(",", ":")) + "\n").encode()
        finally:
            if reader.in_transaction:
                reader.rollback()
            if writer.in_transaction:
                writer.rollback()
            reader.close()
            writer.close()


def main() -> int:
    if sys.stdin.buffer.read():
        sys.stderr.write(
            "protocol_error: SQLite WAL busy-snapshot target requires empty input\n"
        )
        return 2
    try:
        output = _run()
    except (sqlite3.Error, RuntimeError) as exc:
        sys.stderr.write(f"sqlite_wal_busy_snapshot_error: {exc}\n")
        return 1
    sys.stdout.buffer.write(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
