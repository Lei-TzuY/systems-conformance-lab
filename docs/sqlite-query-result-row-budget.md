# SQLite query result-row budget

`SQLiteQueryTarget` treats query cardinality as an untrusted resource dimension. The shared runner's output ceiling only applies after the child process emits bytes, so it cannot prevent SQLite/Python from first materializing a large result set inside the target process.

`SQLiteQueryTarget(max_result_rows=N)` therefore requires a positive integer and encodes that value in worker argv/replay identity. The default is `10_000` rows.

The query worker consumes the SQLite cursor incrementally. It accepts exactly `N` rows, but if SQLite produces row `N+1` the worker stops immediately with exit code `4` and deterministic stderr:

```text
result_error: result exceeds max_result_rows: N
```

The worker does not call `fetchall()`, so a high-cardinality result cannot force the complete row set to be retained before the adapter notices the configured bound. The existing VM-step, wall-clock, stdin, SQL-byte, JSON-depth, and parent output limits remain independent and necessary; the row ceiling does not bound the byte size of one individual SQLite value.

Real-process integration executes a recursive CTE through `DifferentialHarness`: a candidate capped at two rows rejects a three-row result while an oracle capped at three rows succeeds, producing a stable `product_mismatch` rather than an infrastructure failure. Focused coverage also verifies exact-boundary success, deterministic rejection at the next row, invalid configuration rejection, and replay-context differentiation.
