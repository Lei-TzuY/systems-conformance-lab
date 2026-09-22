# SQLite two-connection scenario executor

SQLiteTwoConnectionScenarioTarget is the next SQLite adapter phase after the
repository's fixed one-scenario workers. It executes a bounded, data-driven program over
exactly two independent connections, a and b, to one real temporary file-backed SQLite
database.

The goal is not to turn the conformance package into a general scheduler. The goal is
to make common two-connection ordering semantics executable without adding another
worker module for every reader/writer permutation.

## Input protocol

Each case is one strict JSON document with exactly setup and steps. Setup contains
single SQL statements. Steps are ordered objects selecting connection a or b and one
supported operation.

Supported operations are:

- begin: start deferred, immediate, or exclusive transaction mode;
- try_begin: attempt the same begin modes, retaining a stable SQLite busy error in
  the transcript instead of aborting the scenario;
- execute: run one SQL statement that does not return columns;
- query: run one SQL statement and retain bounded normalized columns and rows;
- try_execute: execute a non-query and retain either success or a recognized SQLite
  busy result, including its extended numeric error code;
- try_query: execute a query and retain either bounded rows or a recognized SQLite
  busy result, including its extended numeric error code;
- commit and rollback: explicitly end the selected connection's transaction.

The worker rejects input SQL whose first executable keyword is transaction control,
ATTACH, DETACH, or PRAGMA. Extension loading is disabled, both live connections use
busy_timeout zero, and input SQL is still protected by the existing SQLite authorizer.
Cases cannot supply database paths.

## Bounded execution contract

The target configuration is encoded in CommandTarget argv and therefore participates in
replay-context identity. Positive ceilings cover setup statement count, scenario step
count, per-statement SQL bytes, aggregate SQL bytes, bind parameter count, query row and
column counts, individual TEXT or BLOB result bytes, normalized per-query result bytes,
and the complete retained semantic transcript.

The outer process runner continues to own stdin, wall-clock, stdout and stderr,
aggregate output, and process-tree bounds. Structural validation and SQL-budget
validation happen before the temporary database is opened.

## Executable evidence

The first integration slice proves two existing classes of behavior through the new
data-driven surface.

First, WAL snapshot visibility: connection a pins value 0, connection b commits value
1, a still reads 0 until its transaction ends, then refreshes to 1.

Second, writer exclusion and recovery: one connection holds a writer transaction,
try_begin on the other records SQLITE_BUSY, release allows the second writer to acquire
and commit, and the same semantic transcript is compared across DELETE and WAL modes
through DifferentialHarness.

These tests execute real child processes and real SQLite files. They are not fixture-only
API tests.

## Scope boundary

This executor does not claim arbitrary concurrent scheduling, fairness, timing
semantics, multi-process crash orchestration, backup or checkpoint coverage, power-loss
durability, or support for more than two live connections. Existing specialized crash
and backup targets remain the evidence source for those contracts.

A later phase may migrate another repeated two-connection scenario only when the generic
program can express it without weakening its existing evidence. The architecture goal is
fewer duplicated orchestration workers, not fewer correctness assertions.


## Consolidated two-connection coverage

The expected-busy operations close the remaining simple two-connection orchestration
gap. The generic executor now carries the executable evidence that was previously split
across dedicated WAL snapshot, WAL busy-snapshot, and reader-contention workers.

The regressions preserve the important distinctions rather than flattening them:

- a stale WAL reader upgrade records SQLITE_BUSY_SNAPSHOT and its extended error code,
  keeps the pinned value visible, then refreshes after rollback;
- a DELETE-mode reader behind an EXCLUSIVE writer records SQLITE_BUSY;
- the same reader step in WAL mode succeeds and observes the last committed value;
- the original WAL snapshot-retention scenario remains covered by ordinary query steps.

Only these simple same-process two-connection workers are consolidated. Crash recovery,
backup, checkpoint, multi-process coordination, and durability workers remain separate
because their process/failure boundaries are not expressible by this executor.


## Structured failure reduction and repro

The two-connection adapter also has a target-specific structured triage path. It does
not add scheduling semantics to the generic harness. Given an already observed fuzz
failure, the SQLite adapter reduces three bounded dimensions in order:

1. ordered scenario steps, while retaining at least one step;
2. setup statements, which may reduce to an empty list;
3. JSON-scalar parameters on retained steps.

Each candidate is executed through DifferentialHarness.preserves_failure and must retain
the exact stable failure signature captured by the original witness. Evaluation and
candidate-enumeration budgets are bounded independently for every phase. A final
write_repro execution revalidates the minimized case under the expected signature before
evidence is published.

The integration regression uses real DELETE and WAL targets whose reader-contention
transcripts differ. It starts from a deliberately noisy scenario, removes irrelevant
steps and setup, simplifies the retained query parameter, writes the minimized repro,
and replays it through the normal repro path. This is reduction of executable evidence,
not a synthetic reducer-only fixture.
