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
    parser.add_argument("--holder-begin", choices=("immediate", "exclusive"), required=True)
    parser.add_argument("--contender-begin", choices=("immediate", "exclusive"), required=True)
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


def _begin(connection: sqlite3.Connection, mode: str) -> None:
    connection.execute(f"BEGIN {mode.upper()}")


def _run(*, journal_mode: str, holder_begin: str, contender_begin: str) -> bytes:
    with tempfile.TemporaryDirectory(prefix="systems-conformance-sqlite-lock-") as directory:
        database = str(Path(directory) / "case.sqlite")
        bootstrap = sqlite3.connect(database, isolation_level=None)
        try:
            bootstrap.execute("CREATE TABLE items(v INTEGER NOT NULL)")
            _set_journal_mode(bootstrap, journal_mode)
        finally:
            bootstrap.close()

        holder = sqlite3.connect(database, isolation_level=None, timeout=0.0)
        contender = sqlite3.connect(database, isolation_level=None, timeout=0.0)
        try:
            _configure_connection(holder)
            _configure_connection(contender)
            _begin(holder, holder_begin)
            holder.execute("INSERT INTO items VALUES (1)")

            blocked_error: str | None = None
            try:
                _begin(contender, contender_begin)
            except sqlite3.OperationalError as exc:
                blocked_error = getattr(exc, "sqlite_errorname", type(exc).__name__)
            else:
                contender.rollback()
                raise RuntimeError("competing writer unexpectedly acquired transaction")

            if blocked_error not in {"SQLITE_BUSY", "SQLITE_BUSY_RECOVERY", "SQLITE_BUSY_SNAPSHOT"}:
                raise RuntimeError(f"competing writer failed unexpectedly: {blocked_error}")

            holder.rollback()
            _begin(contender, contender_begin)
            contender.execute("INSERT INTO items VALUES (2)")
            contender.commit()
            rows = [row[0] for row in contender.execute("SELECT v FROM items ORDER BY v")]
            payload = {
                "blocked": True,
                "blocked_error": blocked_error,
                "retry_acquired": True,
                "rows": rows,
            }
            return (json.dumps(payload, separators=(",", ":")) + "\n").encode()
        finally:
            if holder.in_transaction:
                holder.rollback()
            if contender.in_transaction:
                contender.rollback()
            holder.close()
            contender.close()


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    if sys.stdin.buffer.read():
        sys.stderr.write("protocol_error: SQLite lock target requires empty input\n")
        return 2
    try:
        output = _run(
            journal_mode=args.journal_mode,
            holder_begin=args.holder_begin,
            contender_begin=args.contender_begin,
        )
    except (sqlite3.Error, RuntimeError) as exc:
        sys.stderr.write(f"sqlite_lock_error: {exc}\n")
        return 3
    sys.stdout.buffer.write(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
