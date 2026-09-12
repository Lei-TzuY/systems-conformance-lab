# SQLite WAL partial-reader-release commit contract

`SQLiteWALPartialReaderReleaseCommitTarget` exercises a real file-backed WAL database with two independent reader processes pinning different snapshots.

The scenario is intentionally narrower than a general concurrency model. It verifies one reclamation and visibility invariant after only part of the reader set disappears:

1. initialize value `40` in WAL mode with automatic checkpointing disabled;
2. pin an older reader at snapshot `40`;
3. commit `41`, then pin a newer reader at snapshot `41`;
4. commit `42` and verify both readers retain their own snapshots;
5. prove a truncating checkpoint is busy while both readers are pinned;
6. force-kill the newer reader and prove the older reader still sees `40` and still blocks truncating checkpoint reclamation;
7. commit `43` while the older reader remains pinned;
8. prove the older reader still sees `40`, while a fresh observer sees committed value `43`;
9. prove the new commit did not release the older reader's checkpoint constraint;
10. force-kill the final reader, require checkpoint release, then fresh-reopen the database and require durable value `43`, `integrity_check = ok`, and a non-busy truncating checkpoint.

This target is a process-isolated integration probe, not a SQLite model checker. Its value is the cross-process contract: partial reader cleanup must not over-release WAL retention state, and a surviving stale snapshot must not prevent independent writers from committing newer durable state.

The adapter rejects non-empty input before running the scenario. The focused test also executes the adapter as both candidate and oracle through `DifferentialHarness` so the complete structured-result/comparison path must remain deterministic.
