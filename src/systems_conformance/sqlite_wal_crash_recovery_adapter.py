from __future__ import annotations

import sys
from dataclasses import dataclass

from .harness import CommandTarget


@dataclass(frozen=True, slots=True)
class SQLiteWALCrashRecoveryTarget:
    """Process-isolated SQLite WAL writer-crash recovery target."""

    commit_before_crash: bool = False
    pin_reader_snapshot: bool = False
    checkpoint_after_crash: bool = False

    def as_command_target(self) -> CommandTarget:
        argv = [sys.executable, "-m", "systems_conformance._sqlite_wal_crash_recovery_worker"]
        if self.commit_before_crash:
            argv.append("--commit-before-crash")
        if self.pin_reader_snapshot:
            argv.append("--pin-reader-snapshot")
        if self.checkpoint_after_crash:
            argv.append("--checkpoint-after-crash")
        return CommandTarget(tuple(argv))
