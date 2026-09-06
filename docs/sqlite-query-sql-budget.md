# SQLite query SQL byte budget

`SQLiteQueryTarget` treats SQL text as untrusted target input. In addition to the shared harness stdin ceiling and optional SQLite VM-step budget, every individual setup statement and the query itself now has a deterministic UTF-8 byte ceiling.

`SQLiteQueryTarget(max_sql_bytes=N)` requires a positive integer and encodes the value in the worker argv, so the existing `CommandTarget` replay identity distinguishes otherwise identical targets with different SQL ceilings. The default is 64 KiB per SQL string.

Protocol validation counts `len(sql.encode("utf-8"))` separately for each setup entry and for the query. A string larger than the configured ceiling is rejected with exit code `2` and a deterministic `protocol_error` before the worker opens its in-memory SQLite connection or prepares input-provided SQL. A string exactly at the ceiling remains valid.

This limit complements rather than replaces the shared process runner's input-size limit: the runner bounds the complete JSON request, while `max_sql_bytes` prevents one statement from consuming the entire request budget or driving oversized SQL into SQLite preparation. The normal timeout, output limits, process-tree cleanup, and optional `max_vm_steps` remain independent safety layers.

The focused tests cover exact-bound acceptance, oversized query and setup rejection, and invalid adapter configuration. The real integration test runs the same `SELECT 1` request through `DifferentialHarness` with adjacent 7-byte and 8-byte ceilings. The smaller candidate reports a target-level protocol result while the exact-bound oracle succeeds, producing a stable `product_mismatch` with no infrastructure failure and proving the configured ceiling participates in a real differential path.
