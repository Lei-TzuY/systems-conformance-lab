from __future__ import annotations

import sys
from dataclasses import dataclass

from .harness import CommandTarget


@dataclass(frozen=True, slots=True)
class SQLiteWALPartialReleaseCommittedWriterCrashTarget:
    """Real WAL target validating committed writer durability after partial reader release."""

    def as_command_target(self) -> CommandTarget:
        return CommandTarget(
            (
                sys.executable,
                "-m",
                "systems_conformance._sqlite_wal_partial_release_committed_writer_crash_worker",
            )
        )
