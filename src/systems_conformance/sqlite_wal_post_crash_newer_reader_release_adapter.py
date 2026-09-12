from __future__ import annotations

import sys
from dataclasses import dataclass

from .harness import CommandTarget


@dataclass(frozen=True, slots=True)
class SQLiteWALPostCrashNewerReaderReleaseTarget:
    """Validate newer-reader release after a committed writer crash."""

    def as_command_target(self) -> CommandTarget:
        return CommandTarget(
            (
                sys.executable,
                "-m",
                "systems_conformance._sqlite_wal_post_crash_newer_reader_release_worker",
            )
        )
