# SQLite transaction aggregate parameter byte budget

`SQLiteTransactionTarget.max_param_bytes` bounds the aggregate decoded UTF-8 bytes across all string bind values in each transaction statement and in the final observation statement before SQLite execution. The default ceiling is 4 MiB per statement.

The budget is intentionally separate from `max_params` and `max_param_value_bytes`: cardinality limits the number of bind values, the per-value ceiling rejects one oversized string, and the aggregate ceiling prevents many individually valid strings from accumulating an oversized bind payload. Non-string scalar parameters contribute zero bytes here and remain bounded by `max_params` plus the outer request/input ceilings.

The worker counts decoded UTF-8 bytes, not Python characters or JSON source bytes. For example, two `"é"` values consume four aggregate bytes. A statement exactly at the configured ceiling is accepted; the first string that would push the running total above the ceiling is rejected before SQLite executes that transaction or observation statement with exit code 2 and a deterministic `protocol_error`.

The ceiling is applied independently to every transaction statement and to the observation statement rather than accumulating across the whole program. The configured value is included in the generated command argv, so changing it changes the differential harness replay-context fingerprint and recorded evidence cannot silently cross resource-limit configurations.
