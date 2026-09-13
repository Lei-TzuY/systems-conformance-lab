from __future__ import annotations

import sys
from dataclasses import dataclass

from .harness import CommandTarget


@dataclass(frozen=True, slots=True)
class SQLiteWALBackupUncommittedCrashTarget:
    """Process-isolated detached WAL backup target for uncommitted crash recovery."""

    def as_command_target(self) -> CommandTarget:
        return CommandTarget(
            (
                sys.executable,
                "-m",
                "systems_conformance._sqlite_wal_backup_uncommitted_crash_worker",
            )
        )
