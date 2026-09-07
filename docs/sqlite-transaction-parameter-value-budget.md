# SQLite transaction parameter value byte budget

`SQLiteTransactionTarget(max_param_value_bytes=N)` bounds every decoded string bind parameter in both transaction statements and the final observation statement before SQLite execution. The default is 1 MiB and the value must be a positive integer.

The worker measures the UTF-8 byte length of the decoded string, not Python character count or the escaped JSON representation. A string whose UTF-8 encoding is exactly `N` bytes is accepted; the first string requiring more than `N` bytes is rejected deterministically with protocol exit code 2 and a field-specific error identifying whether the offending bind belongs to `transaction` or `observe`.

The ceiling is encoded in worker argv, so changing it changes the harness replay-context identity. It complements, rather than replaces, the stdin byte ceiling, JSON-depth ceiling, SQL byte ceiling, bind-parameter count ceiling, VM-step budget, process timeout, and result/output budgets.

Focused coverage uses the multibyte value `éé`, which occupies four UTF-8 bytes, to verify the exact 4-byte boundary and deterministic rejection at 3 bytes. Real-process differential coverage runs the same request against SQLite transaction targets configured with 3-byte and 4-byte ceilings and verifies that the bounded side is classified as a product mismatch rather than an infrastructure failure.
