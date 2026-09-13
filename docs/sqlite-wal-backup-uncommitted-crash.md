# SQLite detached WAL backup after uncommitted writer crash

`SQLiteWALBackupUncommittedCrashTarget` validates that an online SQLite backup remains an independently recoverable durable artifact when its own WAL writer is force-killed before commit.

The source starts in WAL mode, advances from `200` to committed `201`, and is copied with SQLite's online backup API. The source then advances independently to `202`; the backup must remain at `201`. The source database and its WAL/SHM sidecars are then deleted so the remaining checks cannot accidentally depend on the original database.

A separate process opens the detached backup in WAL mode, begins an immediate transaction, writes pending value `203`, verifies that the writer itself can observe that pending state, and emits a readiness marker. Only after that marker is observed is the process force-killed. Reopening the detached backup must recover committed `201`, never pending `203`, with `integrity_check=ok` and a non-busy truncating checkpoint.

The recovered backup must remain writable: a follow-up commit to `204` must succeed, survive close/reopen, and retain integrity. This proves rollback of an uncommitted crash and continued durability independently of the now-absent source.

The adapter uses fixed argv-only module execution. Non-empty target input is rejected before database work. `CommandTarget` supplies bounded timeout/output behavior and process-tree cleanup; a real `DifferentialHarness` candidate/oracle regression verifies deterministic execution.

This slice does not claim power-loss durability, storage-controller cache persistence, torn-write recovery, or byte-identical WAL layout.