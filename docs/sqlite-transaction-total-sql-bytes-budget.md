# SQLite transaction total SQL byte budget

`SQLiteTransactionTarget.max_total_sql_bytes` bounds aggregate decoded UTF-8 bytes across every setup statement, transaction statement, and the final observation statement before any SQLite statement executes. The default ceiling is 4 MiB.

This budget complements `max_statements` and per-statement `max_sql_bytes`: statement cardinality limits how many SQL programs a request can contain, the per-statement ceiling rejects one oversized program, and the total ceiling prevents many individually valid statements from accumulating an oversized SQL workload. The outer harness stdin budget remains an independent protection over the complete serialized request.

The worker counts validated decoded SQL text in request order. A request exactly at the configured ceiling is accepted; the statement that would push the cumulative total above the ceiling is rejected with exit code 2 and deterministic `protocol_error: request SQL exceeds max_total_sql_bytes: N` before setup, transaction, or observation execution begins.

The configured value is included in the generated command argv, so changing it changes the differential harness replay-context fingerprint and recorded evidence cannot silently cross SQL-resource configurations.
