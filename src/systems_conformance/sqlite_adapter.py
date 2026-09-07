from __future__ import annotations

import sys
from dataclasses import dataclass

from .harness import CommandTarget

DEFAULT_MAX_JSON_DEPTH = 32
DEFAULT_MAX_SETUP_STATEMENTS = 256
DEFAULT_MAX_RESULT_COLUMNS = 256
DEFAULT_MAX_RESULT_ROWS = 10_000
DEFAULT_MAX_RESULT_VALUE_BYTES = 1024 * 1024
DEFAULT_MAX_RESULT_BYTES = 512 * 1024


@dataclass(frozen=True, slots=True)
class SQLiteQueryTarget:
    """Process-isolated adapter for deterministic SQLite query conformance.

    Inputs are JSON protocol documents consumed by the bundled worker. Each execution
    uses a fresh in-memory database, so fuzz cases cannot leak database state across
    evaluations. SQL still runs as untrusted target input and remains bounded by the
    shared runner's timeout and output limits. ``max_json_depth`` bounds structural JSON
    nesting before Python decoding, ``max_sql_bytes`` bounds every setup/query SQL string
    before SQLite opens the case, ``max_setup_statements`` bounds setup-list cardinality
    before any setup statement executes, ``max_result_columns`` bounds result width before
    row materialization, ``max_result_rows`` bounds result cardinality,
    ``max_result_value_bytes`` bounds each TEXT/BLOB before JSON/hex expansion,
    ``max_result_bytes`` bounds cumulative normalized row JSON bytes before full-result
    serialization, and ``max_vm_steps`` optionally adds a deterministic SQLite
    progress-handler budget below the wall-clock timeout.
    """

    foreign_keys: bool = True
    enable_faults: bool = False
    max_sql_bytes: int = 64 * 1024
    max_json_depth: int = DEFAULT_MAX_JSON_DEPTH
    max_setup_statements: int = DEFAULT_MAX_SETUP_STATEMENTS
    max_result_columns: int = DEFAULT_MAX_RESULT_COLUMNS
    max_result_rows: int = DEFAULT_MAX_RESULT_ROWS
    max_result_value_bytes: int = DEFAULT_MAX_RESULT_VALUE_BYTES
    max_result_bytes: int = DEFAULT_MAX_RESULT_BYTES
    max_vm_steps: int | None = None

    def __post_init__(self) -> None:
        if (
            isinstance(self.max_sql_bytes, bool)
            or not isinstance(self.max_sql_bytes, int)
            or self.max_sql_bytes <= 0
        ):
            raise ValueError("max_sql_bytes must be a positive integer")
        if (
            isinstance(self.max_json_depth, bool)
            or not isinstance(self.max_json_depth, int)
            or self.max_json_depth <= 0
        ):
            raise ValueError("max_json_depth must be a positive integer")
        if (
            isinstance(self.max_setup_statements, bool)
            or not isinstance(self.max_setup_statements, int)
            or self.max_setup_statements <= 0
        ):
            raise ValueError("max_setup_statements must be a positive integer")
        if (
            isinstance(self.max_result_columns, bool)
            or not isinstance(self.max_result_columns, int)
            or self.max_result_columns <= 0
        ):
            raise ValueError("max_result_columns must be a positive integer")
        if (
            isinstance(self.max_result_rows, bool)
            or not isinstance(self.max_result_rows, int)
            or self.max_result_rows <= 0
        ):
            raise ValueError("max_result_rows must be a positive integer")
        if (
            isinstance(self.max_result_value_bytes, bool)
            or not isinstance(self.max_result_value_bytes, int)
            or self.max_result_value_bytes <= 0
        ):
            raise ValueError("max_result_value_bytes must be a positive integer")
        if (
            isinstance(self.max_result_bytes, bool)
            or not isinstance(self.max_result_bytes, int)
            or self.max_result_bytes <= 0
        ):
            raise ValueError("max_result_bytes must be a positive integer")
        if self.max_vm_steps is not None and (
            isinstance(self.max_vm_steps, bool)
            or not isinstance(self.max_vm_steps, int)
            or self.max_vm_steps <= 0
        ):
            raise ValueError("max_vm_steps must be a positive integer or None")

    def as_command_target(self) -> CommandTarget:
        """Return the argv-only CommandTarget used by DifferentialHarness."""
        argv = [
            sys.executable,
            "-m",
            "systems_conformance._sqlite_query_bounded_worker",
            "--max-json-depth",
            str(self.max_json_depth),
            "--foreign-keys" if self.foreign_keys else "--no-foreign-keys",
            "--enable-faults" if self.enable_faults else "--disable-faults",
            "--max-sql-bytes",
            str(self.max_sql_bytes),
            "--max-setup-statements",
            str(self.max_setup_statements),
            "--max-result-columns",
            str(self.max_result_columns),
            "--max-result-rows",
            str(self.max_result_rows),
            "--max-result-value-bytes",
            str(self.max_result_value_bytes),
            "--max-result-bytes",
            str(self.max_result_bytes),
        ]
        if self.max_vm_steps is not None:
            argv.extend(("--max-vm-steps", str(self.max_vm_steps)))
        return CommandTarget(tuple(argv))
