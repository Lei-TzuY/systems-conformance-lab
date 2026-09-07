# SQLite transaction result-row budget

`SQLiteTransactionTarget` treats every statement result as untrusted output cardinality. The parent runner has a hard emitted-output ceiling, but the transaction worker previously called `cursor.fetchall()` first, so a hostile recursive query could materialize an arbitrarily large row set inside the child before that parent boundary became effective.

`SQLiteTransactionTarget(max_result_rows=N)` therefore requires a positive integer, defaults to 10,000 rows, and encodes the budget in worker argv/replay identity. Each transaction statement and the final observation consume the SQLite cursor incrementally. Exactly `N` rows are accepted; observing row `N + 1` stops immediately with exit code `4` and:

```text
result_error: result exceeds max_result_rows: N
```

The ceiling is per executed statement, not a cumulative transcript budget. It complements the statement-count, SQL-byte, JSON-depth, VM-step, wall-clock, stdin, and parent output limits.

Real-process integration uses a recursive CTE that yields three rows. A candidate capped at two rows rejects the third row while an oracle capped at three rows succeeds, and `DifferentialHarness` classifies the difference as a stable `product_mismatch` rather than an infrastructure failure.
