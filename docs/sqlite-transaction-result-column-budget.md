# SQLite transaction result column budget

`SQLiteTransactionTarget` bounds the width of every SQLite result set with `max_result_columns` (default: 256).

The bounded worker checks `cursor.description` immediately after SQLite prepares/executes each transaction statement and the final observation. If the result exposes more than the configured number of columns, the worker stops before row iteration and returns a deterministic product-side result failure:

```text
result_error: result exceeds max_result_columns: N
```

The process exits with code 4. Exact-boundary results with exactly `N` columns are accepted. Statements without a result set have zero columns and are unaffected.

The limit is part of the target argv, so changing it changes the harness replay-context identity. This makes retained repro evidence sensitive to the resource contract used when the failure was observed.

This ceiling complements, rather than replaces, the existing per-statement row, value-byte, aggregate-row-byte, transcript-byte, VM-step, SQL-byte, JSON-depth, stdin, timeout, and parent output budgets. Its purpose is to reject excessively wide result metadata before row materialization begins.
