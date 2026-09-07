# SQLite transaction transcript result budget

`SQLiteTransactionTarget` treats every transaction and observation result as untrusted output. Per-statement row, value, and normalized-row byte ceilings prevent one statement from growing without bound, but a transaction program can contain many individually valid statements whose result objects accumulate in the child before the final transcript is serialized.

`SQLiteTransactionTarget(max_transcript_result_bytes=N)` therefore requires a positive integer, defaults to 1 MiB, and is encoded in worker argv/replay identity. The worker counts the UTF-8 bytes of each complete normalized statement result object using compact deterministic JSON and accumulates that count across transaction statements and the final observation.

The exact cumulative boundary is accepted. The first statement result that would exceed the ceiling stops execution with exit code `4` and:

```text
result_error: transaction transcript results exceed max_transcript_result_bytes: N
```

The check happens immediately after the bounded statement result is produced and before it is returned to the transaction worker for retention in the transcript. It complements the per-statement `max_result_rows`, `max_result_value_bytes`, and `max_result_bytes` limits, the request `max_statements` ceiling, the SQLite VM-step budget, and the parent process hard-output budget.