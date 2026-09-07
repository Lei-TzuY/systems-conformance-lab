# SQLite query aggregate parameter byte budget

`SQLiteQueryTarget.max_param_bytes` bounds the aggregate decoded UTF-8 bytes across all string values in the query `params` array before SQLite execution. The default ceiling is 4 MiB.

The budget is intentionally separate from `max_params` and `max_param_value_bytes`: cardinality limits the number of bind values, the per-value ceiling rejects one oversized string, and the aggregate ceiling prevents many individually valid strings from accumulating an oversized bind payload. Non-string scalar parameters contribute zero bytes here and remain bounded by `max_params` plus the outer request/input ceilings.

The worker counts decoded UTF-8 bytes, not Python characters or JSON source bytes. For example, two `"é"` values consume four aggregate bytes. A request exactly at the configured ceiling is accepted; the first string that would push the running total above the ceiling is rejected before SQLite executes the query with exit code 2 and a deterministic `protocol_error`.

The configured ceiling is included in the generated command argv, so changing it changes the differential harness replay-context fingerprint. This prevents evidence recorded under one aggregate bind budget from being replayed as if target execution limits were unchanged.
