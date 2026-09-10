from __future__ import annotations

import sys
from dataclasses import dataclass

from .harness import CommandTarget


@dataclass(frozen=True, slots=True)
class SQLiteWALSnapshotTarget:
    """Process-isolated long-lived SQLite WAL reader snapshot target."""

    def as_command_target(self) -> CommandTarget:
        return CommandTarget(
            (sys.executable, "-m", "systems_conformance._sqlite_wal_snapshot_worker")
        )
