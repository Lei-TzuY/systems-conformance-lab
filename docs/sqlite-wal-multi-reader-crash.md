# SQLite WAL multi-reader crash checkpoint retention

`SQLiteWALMultiReaderCrashTarget` validates that SQLite WAL checkpoint reclamation state is released incrementally when multiple independent reader processes crash. The target uses a real temporary file-backed WAL database and the existing process-isolated reader worker; test-program input is not interpreted as commands and any non-empty stdin is rejected before database work.

The database begins at value `10`. An older child reader opens a transaction and pins snapshot `10`. A writer commits `11`, then a second child reader starts and pins snapshot `11`. A second writer commits `12`. At that point both reader processes hold snapshots older than the latest committed value, and `PRAGMA wal_checkpoint(TRUNCATE)` must report busy.

The older reader is force-killed without transaction cleanup. A truncating checkpoint must **still** report busy because the newer reader remains alive with its own pinned snapshot. This is the key invariant: cleanup of one crashed reader must not over-release WAL reader state belonging to another process. The newer reader is then force-killed; only after that final reader disappears may the same truncating checkpoint complete non-busy.

After both crash cleanups, a fresh write transaction commits value `13`. Another fresh connection must observe durable value `13`, return exactly `ok` from `PRAGMA integrity_check`, and complete a final truncating checkpoint non-busy. The emitted JSON transcript contains only stable semantic observations—snapshot values, committed values, checkpoint busy states, and integrity status—rather than WAL frame counts or platform-specific process exit codes.

Reader processes are launched through fixed argv-only Python module invocations. The outer `CommandTarget` supplies the normal bounded timeout, aggregate output budget, process-tree cleanup, and infrastructure-failure classification. The adapter therefore exercises real process lifetime boundaries while preserving the repository's untrusted-input and reproducibility contracts.

This slice proves that multiple reader crash cleanup is neither under-released nor over-released at the WAL checkpoint boundary. It does not claim power-loss durability, storage-controller cache persistence, torn-write recovery, or byte-identical WAL layout.
