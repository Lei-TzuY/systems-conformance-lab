# SQLite transaction multi-phase triage

`reduce_sqlite_transaction_failure_to_repro` closes the adapter-specific hand-off from a captured SQLite transaction failure to minimized, replayable evidence without moving SQLite semantics into the generic reducer or harness.

The reducer preserves the exact stable `FailureSignature` at every phase and uses the existing deterministic transaction contracts in an order chosen to unlock later reductions:

1. reduce fault occurrence toward the earliest matching checkpoint;
2. delete setup and transaction statements while keeping a non-empty transaction;
3. simplify transaction and observation scalar parameters.

Each phase runs through the generic `reduce_case` first-improvement loop with its own explicit strictly-decreasing measure and evaluation budget. The output of one phase becomes the validated input to the next phase. A phase therefore cannot silently change a product mismatch into an infrastructure failure, or vice versa.

After the final parameter phase, `DifferentialHarness.write_repro` re-executes the minimized case with the original expected signature before publishing the bundle. Normal replay-context fingerprinting, bounded bundle loading, evidence validation, archive interoperability, and retention rules continue to apply unchanged.

The real-target regression uses process-isolated `SQLiteTransactionTarget` instances with fault injection enabled only for the candidate. A failure initially triggered at transaction occurrence 2 is reduced to occurrence 0, which then permits unrelated transaction/setup statements to be deleted; the surviving scalar parameter is subsequently simplified to `null`. The resulting repro is replayed through the same real child-process harness and must preserve the original stable failure signature.
