from __future__ import annotations

import sys
from dataclasses import dataclass

from .harness import CommandTarget


@dataclass(frozen=True, slots=True)
class SQLiteWALMultiReaderWriterCrashTarget:
    """Real WAL target validating reader retention across writer crash."""

    def as_command_target(self) -> CommandTarget:
        return CommandTarget(
            (
                sys.executable,
                "-m",
                "systems_conformance._sqlite_wal_multi_reader_writer_crash_worker",
            )
        )
