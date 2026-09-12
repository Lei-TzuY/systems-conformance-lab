from __future__ import annotations

import sys
from dataclasses import dataclass

from .harness import CommandTarget


@dataclass(frozen=True, slots=True)
class SQLiteWALNewerReaderCrashTarget:
    """Real WAL target validating older snapshot retention after newer reader crash."""

    def as_command_target(self) -> CommandTarget:
        return CommandTarget((sys.executable, "-m", "systems_conformance._sqlite_wal_newer_reader_crash_worker"))
