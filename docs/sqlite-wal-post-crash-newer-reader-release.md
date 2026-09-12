# SQLite WAL newer-reader release after committed writer crash

`SQLiteWALPostCrashNewerReaderReleaseTarget` validates that releasing the newer reader admitted after a committed writer crash does not over-release WAL state still owned by an older reader.

The target uses a real temporary file-backed SQLite WAL database. An older reader pins value `80`, a normal writer commits `81`, and an independent writer commits `82` before the parent force-kills that writer process. A fresh observer must still see committed value `82`. A new reader is then admitted and pins `82`; another writer commits `83`, leaving the older and post-crash readers on distinct historical snapshots while a truncating checkpoint remains busy.

The post-crash reader is force-released first. The older reader must continue to observe `80`, and `PRAGMA wal_checkpoint(TRUNCATE)` must remain busy. A fresh observer must see `83`. A further independent commit to `84` must succeed while that older snapshot remains pinned; the old reader must still observe `80`, a fresh observer must see `84`, and checkpoint reclamation must still be blocked.

Only after the older reader is force-released may the truncating checkpoint complete non-busy. A fresh reopen must observe durable value `84` with `PRAGMA integrity_check = ok`. A final follow-up commit to `85` and second fresh observation prove the database remains writable and durable after the crash and staged reader cleanup.

The command target accepts no test-program input: any non-empty stdin is rejected before database work. Child processes are launched with fixed argv-only Python module invocations, while the outer `CommandTarget` supplies timeout, output budgets, process-tree cleanup, and infrastructure-failure classification. The emitted transcript contains stable semantic observations rather than WAL frame counts or platform-specific exit codes.

This slice complements the existing post-crash reader-admission contract, which releases the older reader first. Together they verify both cleanup orders for independently owned WAL snapshots after a committed writer crash. It does not claim power-loss durability, torn-write recovery, or storage-controller cache persistence.
