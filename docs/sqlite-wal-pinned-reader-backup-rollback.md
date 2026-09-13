# SQLite WAL pinned-reader backup after uncommitted writer crash

`SQLiteWALPinnedReaderBackupRollbackTarget` validates online-backup visibility after an uncommitted WAL writer is force-killed while an older independent reader keeps a stale snapshot pinned. The target uses a real temporary file-backed SQLite database, fixed argv-only child-process launch, bounded outer `CommandTarget` execution, and rejects non-empty stdin before touching target state.

The source database begins at value `100`. A child reader pins snapshot `100`; a writer then commits `101`. A separate writer process starts `BEGIN IMMEDIATE`, updates the row to pending value `102`, emits its fixed readiness marker, and is force-killed before commit. The stale reader must still see `100`, while a fresh source connection must see committed `101`, proving the pending value did not escape rollback.

With that reader still alive, a truncating checkpoint must remain busy. The target then performs SQLite online backup from a fresh source connection into a separate file. The backup must contain `101`: it may not capture either the stale reader's `100` snapshot or the crashed writer's uncommitted `102`. Backup integrity must pass, the stale reader must remain on `100`, and the backup operation must not release the reader's checkpoint-retention constraint.

The source then commits `103`. A fresh source observer must see `103`, while the already-created backup must remain independently fixed at `101`; checkpoint reclamation must still be blocked until the pinned reader is force-released. Only after that final reader disappears may the truncating checkpoint complete non-busy.

Fresh reopen checks then require source `103`, backup `101`, and `PRAGMA integrity_check = ok` for both files. The backup is independently updated to `104` without changing the source, then the source commits `105` without changing the backup. Final reopen semantics therefore require source `105`, backup `104`, and integrity success on both sides.

This slice connects real WAL rollback, reader-retention ownership, online backup, and post-backup durability independence. It does not claim power-loss durability, torn-write recovery, storage-controller cache persistence, or byte-identical WAL/backup layout.