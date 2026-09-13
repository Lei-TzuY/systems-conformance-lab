from __future__ import annotations

import sys
from dataclasses import dataclass

from .harness import CommandTarget


@dataclass(frozen=True, slots=True)
class SQLiteWALMultiReaderBackupTarget:
    """Process-isolated WAL backup target with two pinned reader generations."""

    def as_command_target(self) -> CommandTarget:
        return CommandTarget(
            (
                sys.executable,
                "-m",
                "systems_conformance._sqlite_wal_multi_reader_backup_worker",
            )
        )
