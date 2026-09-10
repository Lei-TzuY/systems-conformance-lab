from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--journal-mode", choices=("delete", "wal"), required=True)
    return parser.parse_args(argv)


def _set_journal_mode(connection: sqlite3.Connection, journal_mode: str) -> None:
    row = connection.execute(f"PRAGMA journal_mode = {journal_mode.upper()}").fetchone()
    actual = None if row is None else str(row[0]).lower()
    if actual != journal_mode:
        raise RuntimeError(
            f"SQLite journal mode unavailable: requested {journal_mode}, got {actual}"
        )


def _configure_connection(connection: sqlite3.Connection) -> None:
    connection.execute("PRAGMA busy_timeout = 0")


def _read_value(connection: sqlite3.Connection) -> int:
    row = connection.execute("SELECT v FROM items").fetchone()
    if row is None:
        raise RuntimeError("reader observed no row")
    return int(row[0])


def _run(*, journal_mode: str) -> bytes:
    with tempfile.TemporaryDirectory(
        prefix="systems-conformance-sqlite-reader-contention-"
    ) as directory:
        database = str(Path(directory) / "case.sqlite")
        bootstrap = sqlite3.connect(database, isolation_level=None)
        try:
            _set_journal_mode(bootstrap, journal_mode)
            bootstrap.execute("CREATE TABLE items(v INTEGER NOT NULL)")
            bootstrap.execute("INSERT INTO items VALUES (0)")
        finally:
            bootstrap.close()

        writer = sqlite3.connect(database, isolation_level=None, timeout=0.0)
        reader = sqlite3.connect(database, isolation_level=None, timeout=0.0)
        try:
            _configure_connection(writer)
            _configure_connection(reader)
            writer.execute("BEGIN EXCLUSIVE")
            writer.execute("UPDATE items SET v = 1")

            reader_blocked = False
            reader_error: str | None = None
            precommit_value: int | None = None
            try:
                precommit_value = _read_value(reader)
            except sqlite3.OperationalError as exc:
                reader_blocked = True
                reader_error = getattr(exc, "sqlite_errorname", type(exc).__name__)

            if journal_mode == "delete":
                if not reader_blocked:
                    raise RuntimeError("DELETE reader unexpectedly bypassed EXCLUSIVE writer")
                if reader_error not in {
                    "SQLITE_BUSY",
                    "SQLITE_BUSY_RECOVERY",
                    "SQLITE_BUSY_SNAPSHOT",
                }:
                    raise RuntimeError(f"DELETE reader failed unexpectedly: {reader_error}")
            else:
                if reader_blocked:
                    raise RuntimeError(f"WAL reader unexpectedly blocked: {reader_error}")
                if precommit_value != 0:
                    raise RuntimeError(
                        f"WAL reader observed uncommitted value: {precommit_value}"
                    )

            writer.commit()
            postcommit_value = _read_value(reader)
            if postcommit_value != 1:
                raise RuntimeError(
                    f"reader failed to observe committed value: {postcommit_value}"
                )

            payload = {
                "journal_mode": journal_mode,
                "reader_blocked": reader_blocked,
                "reader_error": reader_error,
                "precommit_value": precommit_value,
                "postcommit_value": postcommit_value,
            }
            return (json.dumps(payload, separators=(",", ":")) + "\n").encode()
        finally:
            if writer.in_transaction:
                writer.rollback()
            if reader.in_transaction:
                reader.rollback()
            writer.close()
            reader.close()


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    if sys.stdin.buffer.read():
        sys.stderr.write(
            "protocol_error: SQLite reader contention target requires empty input\n"
        )
        return 2
    try:
        output = _run(journal_mode=args.journal_mode)
    except (sqlite3.Error, RuntimeError) as exc:
        sys.stderr.write(f"sqlite_reader_contention_error: {exc}\n")
        return 3
    sys.stdout.buffer.write(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
