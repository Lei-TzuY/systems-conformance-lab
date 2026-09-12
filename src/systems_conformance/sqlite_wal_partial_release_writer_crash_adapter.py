from __future__ import annotations

import sys
from dataclasses import dataclass

from .harness import CommandTarget


@dataclass(frozen=True, slots=True)
class SQLiteWALPartialReleaseWriterCrashTarget:
    """Real WAL target validating writer rollback after partial reader release."""

    def as_command_target(self) -> CommandTarget:
        return CommandTarget(
            (
                sys.executable,
                "-m",
                "systems_conformance._sqlite_wal_partial_release_writer_crash_worker",
            )
        )
