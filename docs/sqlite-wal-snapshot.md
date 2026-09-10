# SQLite WAL reader snapshot conformance

`SQLiteWALSnapshotTarget` validates one bounded SQLite MVCC-style visibility contract with two independent connections to the same real temporary file-backed WAL database.

The reader starts a transaction and establishes a snapshot by observing value `0`. A separate writer then obtains `BEGIN IMMEDIATE`, updates the row to `1`, and commits while the reader transaction remains open. The reader must continue to observe `0` inside that transaction. Only after the reader ends its transaction may a fresh read observe `1`.

The target executes through the shared process runner, accepts no stdin payload, uses no shell interpolation, sets zero busy timeouts, and emits one bounded deterministic JSON transcript. Tests exercise the real SQLite file/connection behavior and repeat the process target through `DifferentialHarness`.

This capability does not claim scheduler fairness, arbitrary SQL concurrency, rollback-journal snapshot behavior, checkpoint interaction, WAL truncation, multi-process coordination, crash recovery, torn-write behavior, or power-loss durability. It isolates long-lived reader snapshot stability across a concurrent committed writer in WAL mode.
