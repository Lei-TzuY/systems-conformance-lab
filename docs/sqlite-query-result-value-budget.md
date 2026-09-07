# SQLite query result-value budget

`SQLiteQueryTarget` treats each returned TEXT/BLOB value as an untrusted resource dimension. The row ceiling bounds cardinality, but one value can still be large and BLOB normalization doubles its byte representation when converted to hexadecimal.

`SQLiteQueryTarget(max_result_value_bytes=N)` therefore requires a positive integer and encodes the value in worker argv/replay identity. The default is 1 MiB. TEXT is measured as UTF-8 bytes and BLOBs as raw bytes. Values exactly at the ceiling are accepted; the first larger value exits deterministically with code `4` and:

```text
result_error: result value exceeds max_result_value_bytes: N
```

The check runs during row normalization before BLOB hex encoding and before final JSON serialization. It complements, rather than replaces, the result-row, VM-step, wall-clock, stdin, SQL-byte, JSON-depth, and parent output limits.

Real-process integration executes `zeroblob(5)` through `DifferentialHarness`: a candidate capped at four bytes rejects the value while an oracle capped at five bytes succeeds, producing a stable `product_mismatch` rather than an infrastructure failure. Focused coverage also verifies UTF-8 byte accounting, invalid configuration rejection, and replay-context differentiation.
