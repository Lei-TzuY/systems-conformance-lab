# SQLite WAL busy-snapshot conformance

`SQLiteWALBusySnapshotTarget` validates one bounded SQLite WAL isolation contract with two independent connections to the same real temporary file-backed database.

A reader begins a transaction and establishes a snapshot at value `0`. A separate writer obtains `BEGIN IMMEDIATE`, updates the row to `1`, and commits. The stale reader then attempts to upgrade its existing read transaction into a writer. SQLite must reject that upgrade with the extended `SQLITE_BUSY_SNAPSHOT` result rather than allowing the stale snapshot to overwrite newer committed state. The reader must still observe `0` inside its stale transaction; after rollback, a fresh read must observe `1`.

The target executes through the shared process runner, accepts no stdin payload, uses no shell interpolation, sets zero busy timeouts, and emits one bounded deterministic JSON transcript. Focused tests exercise the real SQLite file/connection behavior and repeat the target through `DifferentialHarness`.

This capability does not claim scheduler fairness, arbitrary SQL concurrency, rollback-journal behavior, busy-handler timing, checkpoint interaction, WAL truncation, multi-process coordination, crash recovery, torn-write behavior, or power-loss durability. It isolates stale WAL reader-to-writer upgrade conflict semantics.
