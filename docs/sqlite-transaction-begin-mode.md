# SQLite transaction begin-mode conformance

`SQLiteTransactionTarget.begin_mode` makes SQLite transaction lock-acquisition policy an explicit target dimension instead of always issuing bare `BEGIN`. Supported values are `deferred`, `immediate`, and `exclusive`, mapped to `BEGIN DEFERRED`, `BEGIN IMMEDIATE`, and `BEGIN EXCLUSIVE`.

The worker selects the requested mode before executing any transaction statement. The command target carries the mode explicitly, so differential runs and repro replay do not silently inherit a different SQLite transaction-begin policy.

The integration coverage uses a real temporary file-backed WAL database, performs a real close/reopen observation boundary, and compares IMMEDIATE and EXCLUSIVE against DEFERRED for both commit and rollback programs through `DifferentialHarness`.

This capability validates logical transaction semantics under explicit SQLite begin policies. It does not claim deterministic multi-process scheduling, lock-contention timing, deadlock behavior, power-loss durability, or filesystem crash semantics. Those require separate bounded concurrent-process or fault-model integrations.
