# SQLite transaction synchronous-mode conformance

`SQLiteTransactionTarget.synchronous` makes SQLite's write-synchronization policy an explicit target dimension instead of inheriting the library/platform default. Supported values are `normal` and `full`, mapped to `PRAGMA synchronous = NORMAL` and `PRAGMA synchronous = FULL`.

The worker applies the requested mode after selecting the requested journal mode and verifies SQLite's numeric `PRAGMA synchronous` result before running untrusted setup or transaction SQL. When `reopen_before_observe=True`, the worker reopens the database and reapplies and revalidates both journal and synchronous modes before the observation query.

This is a storage-policy conformance capability, not a power-loss simulator. Matching logical results between NORMAL and FULL across a real close/reopen boundary demonstrate that both configurations execute the same transaction protocol for the tested case; they do not prove equivalent crash durability, torn-write behavior, filesystem ordering, or hardware persistence semantics.

The integration coverage uses a real temporary file-backed WAL database, exercises commit and rollback through `DifferentialHarness`, and checks that NORMAL and FULL preserve the same post-reopen logical observation.