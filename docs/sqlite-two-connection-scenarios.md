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
