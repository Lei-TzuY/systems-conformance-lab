# SQLite query total SQL byte budget

`SQLiteQueryTarget.max_total_sql_bytes` bounds aggregate decoded UTF-8 bytes across every setup statement and the final query before SQLite execution. The default ceiling is 4 MiB.

This budget complements `max_setup_statements` and per-statement `max_sql_bytes`: setup cardinality limits how many setup programs a request can contain, the per-statement ceiling rejects one oversized program, and the total ceiling prevents many individually valid setup statements plus the final query from accumulating an oversized SQL workload. The outer harness stdin budget remains an independent protection over the complete serialized request.

The bounded worker first applies the existing strict protocol and per-statement SQL validation, then sums validated decoded SQL text. A request exactly at the configured ceiling is accepted; a request above the ceiling is rejected with exit code 2 and deterministic `protocol_error: request SQL exceeds max_total_sql_bytes: N` before the base query worker opens SQLite or executes setup/query SQL.

The configured value is included in the generated command argv, so changing it changes the differential harness replay-context fingerprint and recorded evidence cannot silently cross SQL-resource configurations.
