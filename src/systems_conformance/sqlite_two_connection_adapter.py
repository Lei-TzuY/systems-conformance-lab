from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import Literal

from .harness import CommandTarget

DEFAULT_MAX_SETUP_STATEMENTS = 64
DEFAULT_MAX_STEPS = 64
DEFAULT_MAX_SQL_BYTES = 64 * 1024
DEFAULT_MAX_TOTAL_SQL_BYTES = 4 * 1024 * 1024
DEFAULT_MAX_PARAMS = 999
DEFAULT_MAX_RESULT_ROWS = 10_000
DEFAULT_MAX_RESULT_COLUMNS = 256
DEFAULT_MAX_RESULT_VALUE_BYTES = 1024 * 1024
DEFAULT_MAX_RESULT_BYTES = 512 * 1024
DEFAULT_MAX_TRANSCRIPT_BYTES = 1024 * 1024


@dataclass(frozen=True, slots=True)
class SQLiteTwoConnectionScenarioTarget:
    """Process-isolated two-connection SQLite scenario executor.

    Cases describe setup SQL plus an ordered sequence of operations over exactly two
    connections, a and b. The worker owns one temporary file-backed database,
    configures zero busy timeouts, and emits a deterministic semantic transcript.

    The protocol is intentionally smaller than a general concurrency scheduler. It
    supports explicit begin/try-begin, execute/query and try-execute/try-query, commit,
    and rollback operations.
    Structural, SQL, parameter, result, and transcript budgets are encoded in argv so
    the existing CommandTarget replay fingerprint binds them to persisted evidence.
    """

    journal_mode: Literal["delete", "wal"] = "wal"
    max_setup_statements: int = DEFAULT_MAX_SETUP_STATEMENTS
    max_steps: int = DEFAULT_MAX_STEPS
    max_sql_bytes: int = DEFAULT_MAX_SQL_BYTES
    max_total_sql_bytes: int = DEFAULT_MAX_TOTAL_SQL_BYTES
    max_params: int = DEFAULT_MAX_PARAMS
    max_result_rows: int = DEFAULT_MAX_RESULT_ROWS
    max_result_columns: int = DEFAULT_MAX_RESULT_COLUMNS
    max_result_value_bytes: int = DEFAULT_MAX_RESULT_VALUE_BYTES
    max_result_bytes: int = DEFAULT_MAX_RESULT_BYTES
    max_transcript_bytes: int = DEFAULT_MAX_TRANSCRIPT_BYTES

    def __post_init__(self) -> None:
        if self.journal_mode not in {"delete", "wal"}:
            raise ValueError("journal_mode must be 'delete' or 'wal'")
        for name, value in (
            ("max_setup_statements", self.max_setup_statements),
            ("max_steps", self.max_steps),
            ("max_sql_bytes", self.max_sql_bytes),
            ("max_total_sql_bytes", self.max_total_sql_bytes),
            ("max_params", self.max_params),
            ("max_result_rows", self.max_result_rows),
            ("max_result_columns", self.max_result_columns),
            ("max_result_value_bytes", self.max_result_value_bytes),
            ("max_result_bytes", self.max_result_bytes),
            ("max_transcript_bytes", self.max_transcript_bytes),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f"{name} must be a positive integer")

    def as_command_target(self) -> CommandTarget:
        return CommandTarget(
            (
                sys.executable,
                "-m",
                "systems_conformance._sqlite_two_connection_worker",
                "--journal-mode",
                self.journal_mode,
                "--max-setup-statements",
                str(self.max_setup_statements),
                "--max-steps",
                str(self.max_steps),
                "--max-sql-bytes",
                str(self.max_sql_bytes),
                "--max-total-sql-bytes",
                str(self.max_total_sql_bytes),
                "--max-params",
                str(self.max_params),
                "--max-result-rows",
                str(self.max_result_rows),
                "--max-result-columns",
                str(self.max_result_columns),
                "--max-result-value-bytes",
                str(self.max_result_value_bytes),
                "--max-result-bytes",
                str(self.max_result_bytes),
                "--max-transcript-bytes",
                str(self.max_transcript_bytes),
            )
        )
