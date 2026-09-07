# SQLite query parameter value budget

`SQLiteQueryTarget(max_param_value_bytes=N)` bounds each UTF-8 string bind parameter before SQLite execution. The default is 1 MiB and the value must be a positive integer.

The ceiling is measured on the decoded string's UTF-8 byte length rather than Python character count, so multibyte values have deterministic cross-platform boundaries. Exactly `N` bytes are accepted; the next byte is rejected as a protocol error with exit code 2 before the query is executed. Integer, float, boolean, and null parameters remain covered by the existing scalar/range validation and the `max_params` cardinality ceiling.

The budget is carried in the worker argv, so changing it changes replay identity. It complements stdin, JSON-depth, SQL-byte, bind-count, VM-step, result row/column/value/aggregate-byte, timeout, and process-output budgets rather than replacing them.

Real-process integration coverage uses the actual SQLite child process through `DifferentialHarness` and verifies that asymmetric candidate/oracle byte ceilings produce a stable `product_mismatch`, not an infrastructure failure.
