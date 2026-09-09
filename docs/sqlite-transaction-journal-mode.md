# SQLite transaction journal-mode conformance

`SQLiteTransactionTarget` can execute the same bounded transaction request through either SQLite's rollback-journal path (`journal_mode="delete"`) or write-ahead logging path (`journal_mode="wal"`). This is an adapter-level storage-engine dimension: request SQL, comparison, failure classification, fuzz scheduling, reduction, and repro mechanics remain unchanged.

WAL mode always uses an internally managed temporary database file. SQLite cannot provide real WAL semantics for an in-memory `:memory:` database, so the adapter does not silently accept a downgraded journal mode. The worker applies `PRAGMA journal_mode` before installing the untrusted-SQL authorizer and verifies that SQLite reports the requested mode. An unavailable requested mode is reported as a deterministic target result error rather than being treated as a successful conformance execution.

`reopen_before_observe=True` closes the transaction connection after commit or rollback and opens the same database again before the observation query. This makes journal-mode comparisons exercise persistence through a real file reopen rather than only same-connection visibility.

The integration regression runs the same real transaction program under WAL and DELETE modes through `DifferentialHarness`. Both committed and rolled-back cases must produce identical normalized transcripts after reopen. A difference is therefore surfaced through the normal `product_mismatch` path with stable failure identity; process-launch or harness failures remain `infrastructure_failure` as before.

This slice does not claim power-loss durability or simulate a torn write. It establishes a concrete, reproducible cross-journal conformance boundary that later crash/fault adapters can target without adding SQLite semantics to the generic harness.