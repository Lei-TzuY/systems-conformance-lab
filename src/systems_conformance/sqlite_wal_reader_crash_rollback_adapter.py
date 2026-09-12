from __future__ import annotations

import sys
from dataclasses import dataclass

from .harness import CommandTarget


@dataclass(frozen=True, slots=True)
class SQLiteWALReaderCrashRollbackTarget:
    """Real WAL target validating writer rollback after a reader process crash."""

    def as_command_target(self) -> CommandTarget:
        return CommandTarget(
            (sys.executable, "-m", "systems_conformance._sqlite_wal_reader_crash_rollback_worker")
        )
