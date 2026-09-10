from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import Literal

from .harness import CommandTarget


@dataclass(frozen=True, slots=True)
class SQLiteReaderContentionTarget:
    """Process-isolated SQLite reader/writer contention target.

    A real file-backed database is opened by independent writer and reader connections.
    The writer holds an EXCLUSIVE transaction with an uncommitted update while the
    reader probes visibility with a zero busy timeout. DELETE must block the reader;
    WAL must allow the reader to observe the previously committed snapshot. After the
    writer commits, the reader must observe the new committed value.
    """

    journal_mode: Literal["delete", "wal"] = "wal"

    def __post_init__(self) -> None:
        if self.journal_mode not in {"delete", "wal"}:
            raise ValueError("journal_mode must be 'delete' or 'wal'")

    def as_command_target(self) -> CommandTarget:
        return CommandTarget(
            (
                sys.executable,
                "-m",
                "systems_conformance._sqlite_reader_contention_worker",
                "--journal-mode",
                self.journal_mode,
            )
        )
