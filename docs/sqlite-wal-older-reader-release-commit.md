# SQLite WAL commit after older-reader release

`SQLiteWALOlderReaderReleaseCommitTarget` validates the mirror case of partial WAL reader cleanup: releasing the oldest pinned reader must not disturb a newer reader's snapshot or checkpoint constraint, and that surviving newer snapshot must not prevent an independent writer from committing a later durable value.

A real temporary file-backed WAL database starts at `60`. The older reader pins `60`; a writer commits `61`; the newer reader pins `61`; then another writer commits `62`. A truncating checkpoint must report busy while both snapshots are pinned.

The older reader is force-released first. The newer reader must still read `61`, and the truncating checkpoint must remain busy. A fresh writer then commits `63` while that newer snapshot remains pinned. The surviving reader must continue to read `61`, while a fresh observer sees `63`; checkpoint reclamation must remain blocked until the newer reader is finally released.

After the final reader is released, the truncating checkpoint must complete non-busy. A fresh reopen must observe durable value `63`, `PRAGMA integrity_check` must return exactly `ok`, and the final checkpoint must remain non-busy.

The adapter rejects non-empty stdin before database work and runs through the normal argv-only bounded `CommandTarget` execution path. The transcript records stable semantic observations only and is exercised both directly and through a real candidate/oracle `DifferentialHarness` run.
