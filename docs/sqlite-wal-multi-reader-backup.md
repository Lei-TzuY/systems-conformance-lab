# SQLite WAL multi-reader backup after committed writer crash

`SQLiteWALMultiReaderBackupTarget` validates online backup behavior while two independent WAL reader generations remain pinned across a committed writer crash.

The source database begins at value `110`. An older child reader pins snapshot `110`. A writer commits `111`, then a newer child reader pins snapshot `111`. A separate writer process commits `112`; only after the parent observes the committed state is that writer force-killed. Both readers must retain their original snapshots (`110` and `111`) while a fresh connection observes durable `112`.

With both reader generations still alive, `PRAGMA wal_checkpoint(TRUNCATE)` must remain busy. An online backup is then taken from the live source. The backup must contain the latest committed source value `112`, not either stale reader snapshot, and `integrity_check` must return `ok`. The backup operation must not release either reader's checkpoint retention state.

The older reader is then force-released. The newer reader must continue to observe `111`, and checkpoint truncation must still remain busy. A fresh source writer commits `113`; the newer reader must remain on `111`, a fresh source observer must see `113`, and the already-created backup must remain fixed at `112`. This proves that partial reader release, subsequent source progress, and backup independence coexist without over-releasing WAL reader state.

Only after the final newer reader is released may truncating checkpoint complete non-busy. Freshly reopened source and backup databases must retain `113` and `112` respectively with successful integrity checks. An independent backup write to `114` must not change the source, and a source follow-up commit to `115` must not change the backup.

The adapter runs through fixed argv-only Python module execution. Non-empty stdin is rejected before database work. The outer `CommandTarget` supplies bounded timeout/output handling and process-tree cleanup, while the real `DifferentialHarness` integration verifies deterministic candidate/oracle behavior.

This slice specifically covers multi-generation WAL reader retention combined with committed-writer crash recovery and online backup. It does not claim power-loss durability, storage-controller cache persistence, torn-write recovery, or byte-identical WAL layout.
