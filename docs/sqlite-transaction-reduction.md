# SQLite transaction statement reduction

`sqlite_transaction_statement_deletions` is an adapter-specific candidate source for reducing `SQLiteTransactionTarget` JSON cases without falling back to arbitrary byte deletion.

The contract is intentionally narrow:

- transaction statements are considered before setup statements;
- at least one transaction statement is always retained, so every generated candidate keeps the worker's required structural shape;
- setup statements may reduce to an empty list;
- observation, fault specification, parameters, and all other decoded request fields are preserved;
- deletion order is deterministic and coarse-to-fine;
- `sqlite_transaction_statement_count` counts only setup plus transaction statements and therefore gives `reduce_case` an explicit strictly-decreasing measure.

The reducer does not try to infer SQL dependencies or silently rewrite statements. A deletion that makes later SQL invalid is simply rejected by the normal failure-preservation predicate. This keeps SQL semantics in the real target while the generic reducer continues to own only deterministic first-improvement scheduling and evaluation bounds.

A real integration regression runs commit and rollback `SQLiteTransactionTarget` processes against a case containing irrelevant setup and transaction statements. `reduce_case` uses the structured candidates plus `DifferentialHarness.preserves_failure` and converges to the required table creation plus the single state-changing statement while preserving the original stable `product_mismatch` signature.
