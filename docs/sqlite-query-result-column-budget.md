# SQLite query result column budget

`SQLiteQueryTarget` treats result width as an untrusted resource dimension. Row-count, per-value, normalized-row byte, SQL byte, VM-step, and parent output ceilings do not by themselves prevent a query from producing an excessively wide `cursor.description` before row materialization begins.

`SQLiteQueryTarget(max_result_columns=N)` therefore requires a positive integer, defaults to 256, and is encoded in worker argv/replay identity. After SQLite prepares and executes the query, the worker checks `cursor.description` before collecting rows. Exactly `N` columns are accepted; the first wider result fails deterministically with exit code `4` and:

```text
result_error: result exceeds max_result_columns: N
```

The ceiling is intentionally query-result specific. It complements, rather than replaces, the existing SQL, row, value, aggregate row-payload, VM-step, timeout, stdin, and process-output limits.
