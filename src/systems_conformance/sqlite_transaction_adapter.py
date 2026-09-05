from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import Literal

from .harness import CommandTarget


@dataclass(frozen=True, slots=True)
class SQLiteTransactionTarget:
    """Process-isolated SQLite transaction-program conformance target.

    Each input creates a fresh database, applies setup statements in autocommit mode,
    runs one explicit transaction program, finalizes it according to ``finalize``,
    then executes a post-finalization observation query. By default the worker uses an
    in-memory database; ``reopen_before_observe`` switches to an internally managed
    temporary database file and closes/reopens SQLite before the observation. The
    worker emits a deterministic transcript suitable for differential comparison and
    repro replay.
    """

    finalize: Literal["commit", "rollback"] = "commit"
    foreign_keys: bool = True
    enable_faults: bool = False
    reopen_before_observe: bool = False
    max_statements: int = 64
    max_vm_steps: int | None = None

    def __post_init__(self) -> None:
        if self.finalize not in {"commit", "rollback"}:
            raise ValueError("finalize must be 'commit' or 'rollback'")
        if not isinstance(self.enable_faults, bool):
            raise TypeError("enable_faults must be a bool")
        if not isinstance(self.reopen_before_observe, bool):
            raise TypeError("reopen_before_observe must be a bool")
        if (
            isinstance(self.max_statements, bool)
            or not isinstance(self.max_statements, int)
            or self.max_statements <= 0
        ):
            raise ValueError("max_statements must be a positive integer")
        if self.max_vm_steps is not None and (
            isinstance(self.max_vm_steps, bool)
            or not isinstance(self.max_vm_steps, int)
            or self.max_vm_steps <= 0
        ):
            raise ValueError("max_vm_steps must be a positive integer or None")

    def as_command_target(self) -> CommandTarget:
        """Return the argv-only target consumed by ``DifferentialHarness``."""
        argv = [
            sys.executable,
            "-m",
            "systems_conformance._sqlite_transaction_worker",
            "--commit" if self.finalize == "commit" else "--rollback",
            "--foreign-keys" if self.foreign_keys else "--no-foreign-keys",
            "--enable-faults" if self.enable_faults else "--disable-faults",
            (
                "--reopen-before-observe"
                if self.reopen_before_observe
                else "--same-connection-observe"
            ),
            "--max-statements",
            str(self.max_statements),
        ]
        if self.max_vm_steps is not None:
            argv.extend(("--max-vm-steps", str(self.max_vm_steps)))
        return CommandTarget(tuple(argv))
