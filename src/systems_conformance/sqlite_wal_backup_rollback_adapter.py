from __future__ import annotations

import sys
from dataclasses import dataclass

from .harness import CommandTarget


@dataclass(frozen=True, slots=True)
class SQLiteWALBackupRollbackTarget:
    """Detached WAL rollback, committed-crash, and reader-snapshot target.

    The real worker verifies that an uncommitted writer crash rolls back, a later
    committed writer survives an immediate process crash, and a reader transaction
    opened before that commit retains its old snapshot until the reader commits.
    """

    def as_command_target(self) -> CommandTarget:
        return CommandTarget(
            (
                sys.executable,
                "-m",
                "systems_conformance._sqlite_wal_backup_rollback_worker",
            )
        )
