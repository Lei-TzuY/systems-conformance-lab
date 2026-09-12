# SQLite WAL reader-crash writer rollback

`SQLiteWALReaderCrashRollbackTarget` validates a bounded process-crash contract against a real temporary file-backed SQLite WAL database.

A child reader starts a transaction and pins committed value `10`. An independent writer obtains `BEGIN IMMEDIATE` and updates the row to pending value `11` without committing. The reader must still observe snapshot value `10`; the harness then force-kills that reader without transaction cleanup. The already-active writer rolls back and must immediately observe `10` again.

A fresh connection must also observe durable value `10`, pass `PRAGMA integrity_check`, and complete `PRAGMA wal_checkpoint(TRUNCATE)` without a busy result. That same fresh connection then commits value `12`; a second fresh reopen must observe durable `12`, pass integrity checking, and complete another non-busy truncating checkpoint.

This complements the commit-after-reader-crash target by proving that abnormal reader death does not corrupt or implicitly commit an in-flight writer transaction, and that rollback leaves the database reusable for subsequent durable writes. The target accepts only empty input, uses argv rather than shell interpolation, bounds execution through `CommandTarget`, and emits a deterministic JSON transcript suitable for differential replay.
