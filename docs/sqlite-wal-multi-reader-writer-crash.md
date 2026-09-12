# SQLite WAL multi-reader writer-crash retention

`SQLiteWALMultiReaderWriterCrashTarget` validates a bounded process-crash contract against a real temporary file-backed SQLite WAL database with two independent reader processes.

The older reader pins value `30`. A committed writer advances the database to `31`, then a newer reader pins that snapshot. A second committed writer advances the database to `32`. At this point both reader snapshots must remain stable and a truncating checkpoint must report busy.

A separate writer process then obtains `BEGIN IMMEDIATE`, updates the row to pending value `33`, and is force-killed before commit. The uncommitted update must not publish, both reader processes must continue to observe their original snapshots (`30` and `31`), and `PRAGMA wal_checkpoint(TRUNCATE)` must remain busy. This proves that writer crash cleanup does not accidentally release unrelated reader reclamation constraints.

The newer reader is then force-killed. Checkpoint must still remain busy because the older reader is alive. Only after the older reader is also force-killed may truncation complete. Finally, a fresh writer commits `34`; a fresh reopen must observe durable value `34`, `PRAGMA integrity_check` must return `ok`, and a final truncating checkpoint must be non-busy.

The target rejects non-empty stdin and is also exercised through `DifferentialHarness` as identical candidate/oracle processes to verify deterministic structured output through the normal real-process execution boundary.
