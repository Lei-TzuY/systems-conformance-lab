# SQLite query reduction

`sqlite_query_setup_statement_deletions`, `sqlite_query_parameter_reductions`, and `sqlite_query_fault_occurrence_reductions` are adapter-specific candidate sources for reducing `SQLiteQueryTarget` JSON cases without falling back to arbitrary byte deletion.

Setup reduction removes setup statements in deterministic coarse-to-fine order while preserving the final query, params, optional fault, and unrelated request fields. `sqlite_query_setup_statement_count` provides the explicit strictly-decreasing measure used by `reduce_case`; setup may reduce to an empty list.

Scalar parameter reduction changes one query parameter per candidate. Supported SQLite JSON scalars use the same deterministic complexity ordering as the transaction reducer: same-type boundary values are attempted before `null`, and candidates are emitted only when `sqlite_query_parameter_complexity` strictly decreases. SQL text and unrelated request fields remain unchanged.

Fault-occurrence reduction preserves fault operation and kind while probing lower deterministic occurrence boundaries `0`, `1`, and `2`. `sqlite_query_fault_occurrence_complexity` is the validated non-negative occurrence index, or zero when no fault is present. Invalid fault shapes are rejected instead of normalized.

These helpers intentionally do not rewrite SQL or infer dependencies. The real SQLite child process remains the semantic validator, and `DifferentialHarness.preserves_failure` keeps only candidates that retain the exact stable failure signature. Integration regressions prove all three paths against real `SQLiteQueryTarget` processes: setup deletion preserves a row-budget mismatch, scalar reduction preserves an injected query-fault mismatch, and fault occurrence reduction moves a reachable setup fault from occurrence 2 to 0 without changing failure identity.
