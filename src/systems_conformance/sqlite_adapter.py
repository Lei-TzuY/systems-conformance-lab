from __future__ import annotations

import sys
from dataclasses import dataclass

from .harness import CommandTarget


@dataclass(frozen=True, slots=True)
class SQLiteQueryTarget:
    """Process-isolated adapter for deterministic SQLite query conformance.

    Inputs are JSON protocol documents consumed by the bundled worker. Each execution
    uses a fresh in-memory database, so fuzz cases cannot leak database state across
    evaluations. SQL still runs as untrusted target input and remains bounded by the
    shared runner's timeout and output limits. ``max_vm_steps`` optionally adds a
    deterministic SQLite progress-handler budget below the wall-clock timeout.
    """

    foreign_keys: bool = True
    enable_faults: bool = False
    max_vm_steps: int | None = None

    def __post_init__(self) -> None:
        if self.max_vm_steps is not None:
            if isinstance(self.max_vm_steps, bool) or self.max_vm_steps <= 0:
                raise ValueError("max_vm_steps must be a positive integer or None")

    def as_command_target(self) -> CommandTarget:
        """Return the argv-only CommandTarget used by DifferentialHarness."""
        argv = [
            sys.executable,
            "-m",
            "systems_conformance._sqlite_worker",
            "--foreign-keys" if self.foreign_keys else "--no-foreign-keys",
            "--enable-faults" if self.enable_faults else "--disable-faults",
        ]
        if self.max_vm_steps is not None:
            argv.extend(("--max-vm-steps", str(self.max_vm_steps)))
        return CommandTarget(tuple(argv))
