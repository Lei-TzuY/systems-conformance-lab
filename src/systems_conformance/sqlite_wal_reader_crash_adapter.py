from __future__ import annotations

import sys
from dataclasses import dataclass

from .harness import CommandTarget


@dataclass(frozen=True, slots=True)
class SQLiteWALReaderCrashTarget:
    """Real WAL target validating snapshot cleanup after a reader process crash."""

    def as_command_target(self) -> CommandTarget:
        return CommandTarget(
            (sys.executable, "-m", "systems_conformance._sqlite_wal_reader_crash_worker")
        )
