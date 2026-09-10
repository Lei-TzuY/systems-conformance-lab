# SQLite WAL checkpoint contention conformance

`SQLiteWALCheckpointTarget` validates one bounded real SQLite storage/concurrency contract: a long-lived WAL reader snapshot can prevent a truncating checkpoint from completing, and releasing that snapshot permits the same checkpoint to complete.

The process-isolated worker creates a real temporary file-backed WAL database, disables automatic checkpoints for the writer, opens independent reader/writer/checkpoint connections with zero busy timeout, and establishes a reader transaction at value `0`. The writer then commits three updates, leaving value `3` as the latest committed state while the reader still owns its older snapshot.

A `PRAGMA wal_checkpoint(TRUNCATE)` issued on the independent checkpoint connection must report a non-zero busy flag while that reader snapshot is pinned. The reader must still observe `0`. After reader rollback, the same truncating checkpoint must report `busy == 0`, and a fresh read must observe `3`.

The transcript records the blocked and released checkpoint tuples so repeated executions through `DifferentialHarness` also validate deterministic observable behavior. Frame counts are retained as evidence but tests deliberately do not prescribe exact counts across SQLite builds; the conformance invariant is the busy transition and preserved database observations.

The target accepts no test-program input. Any non-empty stdin is rejected before database work, keeping arbitrary SQL outside this specialized concurrency surface. Process timeout, output limits, process-tree cleanup, and infrastructure failure classification remain owned by `CommandTarget` and the shared runner.

This capability does not claim scheduler fairness, checkpoint latency, exact WAL frame counts, WAL file byte layout, crash recovery, torn-write behavior, fsync durability, or power-loss semantics. Those require separate bounded integrations.
