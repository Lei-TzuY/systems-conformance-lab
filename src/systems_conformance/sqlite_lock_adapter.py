from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import Literal

from .harness import CommandTarget


@dataclass(frozen=True, slots=True)
class SQLiteLockContentionTarget:
    """Process-isolated real SQLite writer-lock contention target.

    The worker uses two independent connections to one temporary file-backed database.
    It holds a writer transaction on connection A, verifies that connection B cannot
    acquire a competing writer transaction with a zero busy timeout, releases A, then
    verifies that B can acquire the same transaction mode. This is deterministic lock
    conformance, not scheduler timing or crash-durability simulation.
    """

    journal_mode: Literal["delete", "wal"] = "wal"
    holder_begin: Literal["immediate", "exclusive"] = "immediate"
    contender_begin: Literal["immediate", "exclusive"] = "immediate"

    def __post_init__(self) -> None:
        if self.journal_mode not in {"delete", "wal"}:
            raise ValueError("journal_mode must be 'delete' or 'wal'")
        if self.holder_begin not in {"immediate", "exclusive"}:
            raise ValueError("holder_begin must be 'immediate' or 'exclusive'")
        if self.contender_begin not in {"immediate", "exclusive"}:
            raise ValueError("contender_begin must be 'immediate' or 'exclusive'")

    def as_command_target(self) -> CommandTarget:
        return CommandTarget(
            (
                sys.executable,
                "-m",
                "systems_conformance._sqlite_lock_worker",
                "--journal-mode",
                self.journal_mode,
                "--holder-begin",
                self.holder_begin,
                "--contender-begin",
                self.contender_begin,
            )
        )
