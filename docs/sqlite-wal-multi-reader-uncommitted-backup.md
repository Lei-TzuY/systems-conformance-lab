# SQLite WAL multi-reader backup after uncommitted writer crash

`SQLiteWALMultiReaderUncommittedBackupTarget` validates online backup behavior while two independent WAL reader generations remain pinned across an uncommitted writer crash.

The source begins at `120`. An older reader pins `120`; the source commits `121`; a newer reader pins `121`. A separate writer then begins an immediate transaction, writes pending value `122`, confirms that it can observe the pending mutation, and is force-killed before commit. Both readers must retain their original snapshots (`120` and `121`) while a fresh source connection observes only durable `121`, proving that pending `122` does not leak through crash recovery.

With both readers still alive, truncating checkpoint must remain busy. An online backup is taken from the live source and must contain latest committed value `121`: neither stale reader state `120` nor uncommitted state `122` is acceptable. Backup integrity must be `ok`, and creating the backup must not release either reader's checkpoint retention.

The older reader is then force-released. The newer reader must still observe `121`, and checkpoint must remain busy. The source commits `123`; the newer reader must remain on `121`, a fresh source observer must see `123`, and the existing backup must remain fixed at `121`. Only after the final newer reader is released may truncating checkpoint complete non-busy.

Freshly reopened source and backup databases must retain `123` and `121` respectively with successful integrity checks. An independent backup write to `124` must not affect the source, and a source follow-up commit to `125` must not affect the backup.

The adapter uses fixed argv-only module execution. Non-empty target input is rejected before database work. The outer `CommandTarget` supplies bounded timeout/output handling and process-tree cleanup, while a real `DifferentialHarness` candidate/oracle regression verifies deterministic execution.

This slice covers multi-generation WAL reader retention, uncommitted-writer forced crash rollback, online backup, partial reader release, and source/backup durability independence. It does not claim power-loss durability, storage-controller cache persistence, torn-write recovery, or byte-identical WAL layout.
