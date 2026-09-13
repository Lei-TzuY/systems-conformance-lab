# SQLite WAL backup with a pinned reader after committed writer crash

`SQLiteWALPinnedReaderBackupTarget` validates a real online SQLite backup while an older WAL reader continues to pin a stale snapshot across an independently committed writer crash.

The source begins at value `90`. A child reader pins snapshot `90`, a normal writer commits `91`, and an independent writer commits `92` before being force-killed. The stale reader must continue to observe `90`, while a fresh source connection must observe committed value `92` and a truncating checkpoint must remain busy.

While that reader is still alive, a fresh source connection performs SQLite's online backup into a separate file. The backup must contain the latest committed value `92`, not the stale reader's `90`, and must pass `PRAGMA integrity_check`. Creating the backup must not disturb source reader ownership: the original reader still observes `90` and checkpoint reclamation remains blocked.

A subsequent source commit to `93` must remain invisible to both the stale reader and the already-created backup. The reader still observes `90`, a fresh source observer sees `93`, the backup stays at `92`, and checkpoint reclamation is still busy. Only after the final reader is force-released may the truncating checkpoint become non-busy.

After reader release, both source and backup are reopened and checked independently. The source must retain `93`, the backup must retain `92`, and both must pass integrity checks. A write of `94` to the backup must not change the source, and a later source commit to `95` must not change the backup. Fresh final observations verify durable values `95` and `94` respectively.

The adapter accepts no test-program commands: non-empty stdin fails closed before database work. Child processes use fixed argv module invocations rather than shell interpolation, and the outer `CommandTarget` supplies bounded timeout/output handling and infrastructure-failure classification. A real `DifferentialHarness` integration test repeats the complete target against itself to verify deterministic structured output.

This slice proves that stale WAL snapshot retention, committed-writer crash recovery, online backup visibility, and source/backup independence compose correctly. It does not claim power-loss durability, storage-cache persistence, or byte-identical database/WAL layouts.
