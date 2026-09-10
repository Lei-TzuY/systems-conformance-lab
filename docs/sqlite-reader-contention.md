# SQLite reader/writer contention

`SQLiteReaderContentionTarget` validates one bounded, real SQLite concurrency contract with two independent connections to the same temporary file-backed database.

The writer opens `BEGIN EXCLUSIVE`, updates a previously committed row, and keeps that write uncommitted while a zero-busy-timeout reader probes the row. In rollback-journal (`DELETE`) mode, the reader must fail with SQLite's busy lock result. In WAL mode, the reader must remain available and observe the previously committed value rather than the writer's uncommitted update. After the writer commits, a fresh autocommit read on the reader connection must observe the new value.

The target executes through the shared `CommandTarget` process runner, accepts no stdin payload, uses no shell interpolation, and emits one bounded JSON transcript. Tests exercise both journal layouts against real SQLite files and repeat the WAL path through `DifferentialHarness` to verify deterministic process-level output.

This capability intentionally does not claim scheduler fairness, busy-handler timing, arbitrary SQL concurrency, long-lived reader transaction behavior, deadlock detection, multi-process coordination, crash recovery, torn-write behavior, or power-loss durability. It isolates the reader availability and committed-snapshot distinction while an EXCLUSIVE writer is active.
