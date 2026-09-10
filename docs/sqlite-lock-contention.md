# SQLite writer-lock contention conformance

`SQLiteLockContentionTarget` exercises a real file-backed SQLite database through two independent connections. Connection A acquires an `IMMEDIATE` or `EXCLUSIVE` writer transaction and performs an uncommitted write. Connection B has `busy_timeout=0` and must fail immediately with `SQLITE_BUSY` when it attempts a competing writer transaction. After A rolls back, B retries the same begin mode, writes, commits, and verifies the resulting row.

The target supports both rollback-journal (`delete`) and WAL storage. `DifferentialHarness` integration compares their deterministic writer-exclusion transcript through the ordinary process runner, so lock behavior participates in the same structured-result and failure-classification path as other targets.

This contract intentionally covers writer-lock exclusion and release/reacquisition only. It does not claim scheduler fairness, busy-handler timing, reader/writer overlap, deadlock detection, process-crash recovery, or power-loss durability. The worker accepts no SQL or other request payload; non-empty stdin is rejected before touching SQLite, keeping this slice narrowly focused on storage-engine locking semantics.
