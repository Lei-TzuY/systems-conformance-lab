# SQLite WAL partial-release writer-crash contract

`SQLiteWALPartialReleaseWriterCrashTarget` exercises a real file-backed WAL database with two independent reader processes, then combines partial reader cleanup with an uncommitted writer crash.

The bounded contract is:

1. initialize value `50` in WAL mode with automatic checkpointing disabled;
2. pin an older reader at `50`;
3. commit `51`, pin a newer reader at `51`, then commit `52`;
4. prove a truncating checkpoint is busy while both readers are pinned;
5. force-release the newer reader and prove the older reader still sees `50` and still blocks truncating checkpoint reclamation;
6. start a writer, acquire `BEGIN IMMEDIATE`, update the pending value to `53`, and force-kill that writer before commit;
7. prove the surviving older reader still sees `50`, a fresh observer still sees committed value `52`, and checkpoint reclamation remains blocked by the surviving reader;
8. release the final reader and require the checkpoint constraint to clear;
9. commit `54`, then fresh-reopen and require durable value `54`, `integrity_check = ok`, and a non-busy truncating checkpoint.

This target verifies that partial reader cleanup does not weaken WAL rollback isolation: crashing an uncommitted writer after one reader disappears must neither publish the pending write nor accidentally release the remaining reader's reclamation constraint. It also proves that normal durable progress resumes after all pinned readers are gone.

The adapter rejects non-empty input before running the scenario. Focused tests exercise the structured transcript and run the same real target as candidate and oracle through `DifferentialHarness` to require deterministic execution.
