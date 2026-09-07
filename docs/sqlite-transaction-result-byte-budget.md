# SQLite transaction result byte budget

`SQLiteTransactionTarget` treats every statement result as untrusted output. Existing row-count and per-value ceilings prevent unbounded cardinality and individual oversized TEXT/BLOB values, but many individually small values can still accumulate a large normalized `rows` payload inside the child before the parent process output ceiling becomes effective.

`SQLiteTransactionTarget(max_result_bytes=N)` therefore requires a positive integer, defaults to 512 KiB, and encodes the budget in worker argv/replay identity. The budget applies independently to every transaction statement and the final observation.

The budget measures the UTF-8 byte length of the compact JSON representation of that statement's normalized `rows` array, including row/value separators and array delimiters. Values first pass the existing deterministic SQLite normalization and per-value ceiling. An empty result therefore costs two bytes (`[]`). The exact boundary is accepted; the first value that would make the rows payload exceed the configured ceiling stops cursor consumption with exit code `4` and:

```text
result_error: result exceeds max_result_bytes: N
```

The check runs while the SQLite cursor is consumed, before the complete statement result or transaction transcript is serialized. It complements rather than replaces `max_result_rows`, `max_result_value_bytes`, the VM-step budget, and the parent process output budget.