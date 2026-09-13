from __future__ import annotations

import sys
from dataclasses import dataclass

from .harness import CommandTarget


@dataclass(frozen=True, slots=True)
class DurablePublishCrashTarget:
    """Process-isolated target for durable file publication crash boundaries."""

    def as_command_target(self) -> CommandTarget:
        return CommandTarget(
            (
                sys.executable,
                "-m",
                "systems_conformance._durable_publish_crash_worker",
            )
        )
