# SQLite transaction result value budget

`SQLiteTransactionTarget` treats every SQLite result value as untrusted output. The parent process runner already limits emitted stdout/stderr and the transaction adapter limits rows per statement, but neither boundary prevents one SQLite `TEXT` or `BLOB` value from becoming very large inside the child first. BLOB normalization is especially important because hex encoding doubles its representation size.

`SQLiteTransactionTarget(max_result_value_bytes=N)` requires a positive integer, defaults to 1 MiB, and encodes the budget in worker argv/replay identity. Every value returned by a transaction statement or the final observation is checked before normalization: `TEXT` is measured as UTF-8 bytes and `BLOB` as raw bytes. Values exactly at the ceiling are accepted. The first larger value stops transcript construction with exit code `4` and:

```text
result_error: result value exceeds max_result_value_bytes: N
```

This is a deterministic target/product result, not a harness infrastructure failure. The ceiling complements `max_result_rows`: row count bounds result cardinality while this budget bounds individual variable-width values. The parent output ceiling remains the final protection for the serialized transcript as a whole.