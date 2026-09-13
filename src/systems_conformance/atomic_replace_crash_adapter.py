from __future__ import annotations

import sys
from dataclasses import dataclass

from .harness import CommandTarget


@dataclass(frozen=True, slots=True)
class AtomicReplaceCrashTarget:
    """Process-isolated target for atomic file publication crash boundaries."""

    def as_command_target(self) -> CommandTarget:
        return CommandTarget(
            (
                sys.executable,
                "-m",
                "systems_conformance._atomic_replace_crash_worker",
            )
        )
