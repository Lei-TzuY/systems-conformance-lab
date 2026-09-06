# SQLite transaction reduction

`sqlite_transaction_statement_deletions` and `sqlite_transaction_parameter_reductions` are adapter-specific candidate sources for reducing `SQLiteTransactionTarget` JSON cases without falling back to arbitrary byte deletion.

Statement reduction keeps a narrow structural contract:

- transaction statements are considered before setup statements;
- at least one transaction statement is always retained, so every generated candidate keeps the worker's required structural shape;
- setup statements may reduce to an empty list;
- observation, fault specification, parameters, and all other decoded request fields are preserved;
- deletion order is deterministic and coarse-to-fine;
- `sqlite_transaction_statement_count` counts only setup plus transaction statements and therefore gives `reduce_case` an explicit strictly-decreasing measure.

Scalar parameter reduction complements that structural pass. Transaction parameters are considered before observation parameters, one scalar changes per candidate, and SQL text plus unrelated request fields remain untouched. `sqlite_transaction_parameter_complexity` assigns a deterministic non-negative complexity to supported JSON scalars; generated candidates are emitted only when that measure is strictly smaller. Same-type boundary values are attempted before `null`, so a reducer can retain a type-sensitive SQLite behavior when the failure predicate requires it while still having a deterministic path toward a minimal witness.

The reducer does not infer SQL dependencies, rewrite SQL, or treat target errors as successful reductions. A structural deletion or scalar simplification that changes the stable failure signature is rejected by the normal failure-preservation predicate. This keeps SQLite semantics in the real target while the generic reducer owns only deterministic first-improvement scheduling and evaluation bounds.

Integration regressions use real commit and rollback `SQLiteTransactionTarget` processes. The statement test converges from irrelevant setup and transaction statements to the required table creation plus one state-changing statement. The scalar test starts with a large bound INSERT parameter and reduces it while preserving the same stable `product_mismatch`, demonstrating that fuzz-discovered parameter witnesses can now flow into deterministic reduction rather than remaining opaque JSON blobs.
