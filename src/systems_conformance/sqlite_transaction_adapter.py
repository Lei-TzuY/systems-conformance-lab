from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import Literal

from .harness import CommandTarget

DEFAULT_MAX_SQL_BYTES = 64 * 1024
DEFAULT_MAX_TOTAL_SQL_BYTES = 4 * 1024 * 1024
DEFAULT_MAX_JSON_DEPTH = 32
DEFAULT_MAX_PARAMS = 999
DEFAULT_MAX_PARAM_VALUE_BYTES = 1024 * 1024
DEFAULT_MAX_PARAM_BYTES = 4 * 1024 * 1024
DEFAULT_MAX_RESULT_ROWS = 10_000
DEFAULT_MAX_RESULT_COLUMNS = 256
DEFAULT_MAX_RESULT_VALUE_BYTES = 1024 * 1024
DEFAULT_MAX_RESULT_BYTES = 512 * 1024
DEFAULT_MAX_TRANSCRIPT_RESULT_BYTES = 1024 * 1024


@dataclass(frozen=True, slots=True)
class SQLiteTransactionTarget:
    """Process-isolated SQLite transaction-program conformance target.

    Each input creates a fresh database, applies setup statements in autocommit mode,
    runs one explicit transaction program, finalizes it according to ``finalize``,
    then executes a post-finalization observation query. ``journal_mode`` selects a
    concrete SQLite rollback-journal (``delete``) or WAL storage path, while
    ``synchronous`` selects SQLite's ``NORMAL`` or ``FULL`` durability policy. By
    default the delete-mode worker uses an in-memory database; WAL always uses an
    internally managed temporary database file because SQLite cannot provide real WAL
    semantics for ``:memory:``. ``reopen_before_observe`` also selects a file-backed
    database and closes/reopens SQLite before the observation. The worker emits a
    deterministic transcript suitable for differential comparison and repro replay.

    ``max_total_sql_bytes`` bounds aggregate decoded UTF-8 SQL bytes across setup,
    transaction, and observation statements before SQLite execution, ``max_params``
    bounds each transaction/observation statement's bind cardinality,
    ``max_param_value_bytes`` bounds each string bind by its decoded UTF-8 byte length,
    ``max_param_bytes`` bounds aggregate decoded UTF-8 bytes across all string binds in
    each transaction or observation statement, ``max_result_columns`` bounds each
    statement's result width before row materialization, ``max_result_rows`` bounds each
    statement's result cardinality before the child materializes the full result set,
    ``max_result_value_bytes`` bounds each TEXT/BLOB value before UTF-8/hex serialization
    expansion, ``max_result_bytes`` bounds each statement's compact normalized ``rows``
    JSON payload, and ``max_transcript_result_bytes`` bounds the cumulative compact JSON
    bytes of all transaction and observation statement result objects before the full
    transcript is retained and serialized.
    """

    finalize: Literal["commit", "rollback"] = "commit"
    foreign_keys: bool = True
    enable_faults: bool = False
    reopen_before_observe: bool = False
    journal_mode: Literal["delete", "wal"] = "delete"
    synchronous: Literal["normal", "full"] = "full"
    max_statements: int = 64
    max_sql_bytes: int = DEFAULT_MAX_SQL_BYTES
    max_total_sql_bytes: int = DEFAULT_MAX_TOTAL_SQL_BYTES
    max_json_depth: int = DEFAULT_MAX_JSON_DEPTH
    max_params: int = DEFAULT_MAX_PARAMS
    max_param_value_bytes: int = DEFAULT_MAX_PARAM_VALUE_BYTES
    max_param_bytes: int = DEFAULT_MAX_PARAM_BYTES
    max_result_rows: int = DEFAULT_MAX_RESULT_ROWS
    max_result_columns: int = DEFAULT_MAX_RESULT_COLUMNS
    max_result_value_bytes: int = DEFAULT_MAX_RESULT_VALUE_BYTES
    max_result_bytes: int = DEFAULT_MAX_RESULT_BYTES
    max_transcript_result_bytes: int = DEFAULT_MAX_TRANSCRIPT_RESULT_BYTES
    max_vm_steps: int | None = None

    def __post_init__(self) -> None:
        if self.finalize not in {"commit", "rollback"}:
            raise ValueError("finalize must be 'commit' or 'rollback'")
        if not isinstance(self.foreign_keys, bool):
            raise TypeError("foreign_keys must be a bool")
        if not isinstance(self.enable_faults, bool):
            raise TypeError("enable_faults must be a bool")
        if not isinstance(self.reopen_before_observe, bool):
            raise TypeError("reopen_before_observe must be a bool")
        if self.journal_mode not in {"delete", "wal"}:
            raise ValueError("journal_mode must be 'delete' or 'wal'")
        if self.synchronous not in {"normal", "full"}:
            raise ValueError("synchronous must be 'normal' or 'full'")
        if (
            isinstance(self.max_statements, bool)
            or not isinstance(self.max_statements, int)
            or self.max_statements <= 0
        ):
            raise ValueError("max_statements must be a positive integer")
        if (
            isinstance(self.max_sql_bytes, bool)
            or not isinstance(self.max_sql_bytes, int)
            or self.max_sql_bytes <= 0
        ):
            raise ValueError("max_sql_bytes must be a positive integer")
        if (
            isinstance(self.max_total_sql_bytes, bool)
            or not isinstance(self.max_total_sql_bytes, int)
            or self.max_total_sql_bytes <= 0
        ):
            raise ValueError("max_total_sql_bytes must be a positive integer")
        if (
            isinstance(self.max_json_depth, bool)
            or not isinstance(self.max_json_depth, int)
            or self.max_json_depth <= 0
        ):
            raise ValueError("max_json_depth must be a positive integer")
        if (
            isinstance(self.max_params, bool)
            or not isinstance(self.max_params, int)
            or self.max_params <= 0
        ):
            raise ValueError("max_params must be a positive integer")
        if (
            isinstance(self.max_param_value_bytes, bool)
            or not isinstance(self.max_param_value_bytes, int)
            or self.max_param_value_bytes <= 0
        ):
            raise ValueError("max_param_value_bytes must be a positive integer")
        if (
            isinstance(self.max_param_bytes, bool)
            or not isinstance(self.max_param_bytes, int)
            or self.max_param_bytes <= 0
        ):
            raise ValueError("max_param_bytes must be a positive integer")
        if (
            isinstance(self.max_result_rows, bool)
            or not isinstance(self.max_result_rows, int)
            or self.max_result_rows <= 0
        ):
            raise ValueError("max_result_rows must be a positive integer")
        if (
            isinstance(self.max_result_columns, bool)
            or not isinstance(self.max_result_columns, int)
            or self.max_result_columns <= 0
        ):
            raise ValueError("max_result_columns must be a positive integer")
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
        if (
            isinstance(self.max_transcript_result_bytes, bool)
            or not isinstance(self.max_transcript_result_bytes, int)
            or self.max_transcript_result_bytes <= 0
        ):
            raise ValueError("max_transcript_result_bytes must be a positive integer")
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
            "systems_conformance._sqlite_transaction_bounded_worker",
            "--commit" if self.finalize == "commit" else "--rollback",
            "--foreign-keys" if self.foreign_keys else "--no-foreign-keys",
            "--enable-faults" if self.enable_faults else "--disable-faults",
            (
                "--reopen-before-observe"
                if self.reopen_before_observe
                else "--same-connection-observe"
            ),
            "--journal-mode",
            self.journal_mode,
            "--synchronous",
            self.synchronous,
            "--max-statements",
            str(self.max_statements),
            "--max-sql-bytes",
            str(self.max_sql_bytes),
            "--max-total-sql-bytes",
            str(self.max_total_sql_bytes),
            "--max-json-depth",
            str(self.max_json_depth),
            "--max-params",
            str(self.max_params),
            "--max-param-value-bytes",
            str(self.max_param_value_bytes),
            "--max-param-bytes",
            str(self.max_param_bytes),
            "--max-result-rows",
            str(self.max_result_rows),
            "--max-result-columns",
            str(self.max_result_columns),
            "--max-result-value-bytes",
            str(self.max_result_value_bytes),
            "--max-result-bytes",
            str(self.max_result_bytes),
            "--max-transcript-result-bytes",
            str(self.max_transcript_result_bytes),
        ]
        if self.max_vm_steps is not None:
            argv.extend(("--max-vm-steps", str(self.max_vm_steps)))
        return CommandTarget(tuple(argv))