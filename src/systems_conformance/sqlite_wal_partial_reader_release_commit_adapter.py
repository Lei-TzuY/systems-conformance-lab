from __future__ import annotations

import sys
from dataclasses import dataclass

from .harness import CommandTarget


@dataclass(frozen=True, slots=True)
class SQLiteWALPartialReaderReleaseCommitTarget:
    """Real WAL target validating commits after partial reader release."""

    def as_command_target(self) -> CommandTarget:
        return CommandTarget(
            (
                sys.executable,
                "-m",
                "systems_conformance._sqlite_wal_partial_reader_release_commit_worker",
            )
        )
