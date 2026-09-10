# SQLite WAL crash recovery conformance

`SQLiteWALCrashRecoveryTarget` validates one bounded real SQLite recovery contract: an uncommitted WAL writer that is force-terminated after acquiring the write transaction must not publish its update, and the database must remain writable after recovery.

The process-isolated target creates a real temporary file-backed WAL database with committed value `0`, then launches a separate writer process with argv-only `subprocess.Popen`. The writer opens an independent connection, executes `BEGIN IMMEDIATE`, updates the row to `1` without committing, and emits a single `READY` handshake only after that uncommitted state exists. The parent force-terminates the writer at that deterministic checkpoint and waits for the process to exit before reopening the database.

Recovery must observe the previously committed value `0`; seeing `1` is a conformance failure. The reopened connection must then be able to acquire a fresh write transaction, commit value `2`, and read `2` back. The emitted JSON transcript records only stable semantic observations rather than platform-specific process exit codes or WAL frame/layout details, so repeated executions can be compared through `DifferentialHarness`.

The target accepts no test-program input. Any non-empty stdin is rejected before database work. It never interpolates input into a shell command. The outer `CommandTarget` continues to own timeout, output-budget, process-tree cleanup, and infrastructure-failure classification for the target process.

This slice does not claim power-loss durability, fsync persistence, torn-write behavior, corruption recovery, checkpoint recovery, committed-transaction survival across storage failure, or byte-identical WAL layout. Those require separate bounded integrations with stronger storage/fault control.