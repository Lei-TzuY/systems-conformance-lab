from __future__ import annotations

import sys
from dataclasses import dataclass

from .harness import CommandTarget


@dataclass(frozen=True, slots=True)
class SQLiteWALPinnedReaderBackupRollbackTarget:
    """Process-isolated WAL backup target after an uncommitted writer crash."""

    def as_command_target(self) -> CommandTarget:
        return CommandTarget(
            (
                sys.executable,
                "-m",
                "systems_conformance._sqlite_wal_pinned_reader_backup_rollback_worker",
            )
        )