# SQLite WAL backup recovery

`SQLiteWALBackupRecoveryTarget` validates a bounded, real-process recovery/export lifecycle using Python's bundled SQLite binding.

The target creates a file-backed WAL database containing value `0`, disables automatic checkpointing, then launches a separate writer process. The writer begins an immediate transaction, updates the row to `1`, commits, and emits `COMMITTED_READY`. Only after that acknowledgement does the parent force-terminate the writer, modeling process loss after commit but before normal connection shutdown.

The parent reopens the database and must recover value `1`, commits a fresh value `2`, successfully runs `PRAGMA wal_checkpoint(TRUNCATE)`, and requires `PRAGMA integrity_check` to return exactly `ok`. It then launches a fresh backup process using a fixed argv-only module invocation. That child opens the recovered source database and a new destination database and uses SQLite's online backup API to copy the source into the destination. The child validates value `2` and `integrity_check=ok` in the destination before reporting `BACKUP_OK`.

After the child exits, the parent independently reopens the produced backup and again requires value `2` and `integrity_check=ok`. It then keeps source and backup open as separate connections and proves the copy boundary in both directions: committing value `3` to the recovered source must leave the backup at `2`, and committing value `4` to the backup must leave the source at `3`. Both databases must still pass `PRAGMA integrity_check` after these independent writes. This verifies that the exported database is a standalone writable artifact rather than an alias or observation that remains coupled to the recovered source.

The emitted transcript contains only stable semantic observations, so two executions can be compared through `DifferentialHarness` without depending on temporary paths, process IDs, WAL frame counts, or platform-specific termination codes.

The target accepts no test-program input. Non-empty stdin fails closed before database work. Writer and backup subprocesses use fixed argv arrays with no shell interpolation, disconnected stdin, captured output, explicit timeouts where bounded waits are required, and deterministic result validation.

This slice proves that an acknowledged WAL commit can survive writer process loss, remain writable and checkpointable, be exported through SQLite's online backup API into a structurally valid database, and yield source and backup databases whose later writes are independent. It does not claim power-loss durability, storage-controller cache persistence, fsync guarantees under hardware failure, torn-write behavior, or corruption recovery.
