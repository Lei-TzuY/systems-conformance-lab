# SQLite query setup statement budget

`SQLiteQueryTarget.max_setup_statements` bounds the number of setup statements accepted by one query request. The default ceiling is 256 statements.

The worker validates the complete `setup` list cardinality immediately after protocol decoding and before validating or executing individual setup SQL strings. An input containing more than the configured ceiling is rejected deterministically with exit code 2 and:

```text
protocol_error: setup exceeds max_setup_statements: N
```

The exact boundary is accepted. The ceiling is encoded in the target argv, so changing it changes the harness replay-context fingerprint and prevents accidental replay under a different execution contract.

This limit complements, rather than replaces, the per-statement SQL byte ceiling, stdin byte budget, deterministic SQLite VM-step budget, wall-clock timeout, and output/result budgets. It specifically prevents a request from converting many individually small setup statements into unbounded setup orchestration work.
