# Conformance substrate stability checkpoint

This document records the bounded architecture checkpoint for `systems-conformance-lab` after the deterministic fault controller and differential-harness integration work.

The goal of this checkpoint is not feature completeness. It is to make the reusable correctness substrate explicit enough that downstream systems repositories can depend on stable responsibilities without pulling product-specific semantics into the core package.

## Stable responsibility layers

| Layer | Current responsibility | Intentionally outside this layer |
| --- | --- | --- |
| `runner` | safe argv execution, stdin bytes, timeout/process-tree cleanup, bounded stream capture, structured execution records | target protocol semantics, output normalization |
| `comparator` | deterministic observable-result comparison and product-vs-infrastructure classification | domain-aware equivalence rules |
| `failure` | stable failure-class identity excluding volatile diagnostics | root-cause inference |
| `fuzz` | deterministic bounded case scheduling and first-failure capture | generators, mutators, corpus policy, coverage guidance |
| `reducer` | deterministic first-improvement loop with explicit progress/budget | domain-specific shrink candidates and measures |
| `repro` / `retention` | deterministic evidence bundles and safe bounded retention | artifact upload/storage services |
| `fault` | deterministic logical-operation trigger intent | kill/corrupt/drop/delay side effects and target-specific failure mapping |
| `harness` | immutable command-target snapshots; candidate/oracle execution; comparison; failure-signature preservation; repro publication | case generation, mutation, concrete fault behavior, target lifecycle orchestration |

## Integrated real-target path

The repository now exercises one complete real-process path rather than validating every primitive only in isolation:

1. deterministic input bytes are selected by `run_fuzz_campaign`;
2. `DifferentialHarness.compare` executes candidate and oracle `CommandTarget` processes through `run_process`;
3. `compare_results` classifies the pair;
4. `failure_signature` captures stable mismatch identity;
5. `reduce_case` calls `DifferentialHarness.preserves_failure` while deleting input bytes;
6. `DifferentialHarness.write_repro` re-evaluates the minimized input and rejects optional signature drift;
7. `write_repro_bundle` persists the exact minimized bytes plus structured candidate/oracle/comparison/signature records.

The end-to-end regression uses actual child processes and therefore covers the integration contract between process execution, result classification, reduction identity, and reproducer publication.

## Invariants at this checkpoint

The following are treated as cross-module invariants rather than individual implementation details:

- shell execution is never required for command targets;
- caller-owned argv/env containers cannot mutate an already-created `CommandTarget`;
- infrastructure failures are never silently downgraded into product mismatches;
- matching comparisons never carry a failure signature;
- reducer preservation compares stable failure signatures rather than output text or exception messages;
- repro publication requires a currently failing input;
- optional expected-signature checking prevents a reducer or later rerun from publishing a different failure class under the original identity;
- fuzz and reduction budgets remain explicit and deterministic;
- concrete fault side effects remain outside `FaultController` and `DifferentialHarness`;
- target-specific normalization, generation, mutation, and lifecycle rules remain adapter responsibilities.

## Integration review conclusions

The existing primitives are sufficiently separated to remain independently reusable. The missing architectural piece was not another fuzzing or fault feature; it was a narrow composition boundary proving that the primitives work together against real process targets.

`DifferentialHarness` is therefore deliberately small. It does not become a scheduler, corpus manager, mutation engine, fault backend, or product plugin registry. Downstream repositories should build thin adapters around this boundary and keep their own semantic knowledge local.

## Deferred architecture phases

The following are not part of the current checkpoint and should not be added merely to create activity:

- coverage-guided or evolutionary fuzzing;
- protocol/filesystem/compiler-specific generators in the core package;
- symbolic/concolic execution;
- distributed worker scheduling;
- process-kill, disk-corruption, packet-loss, clock, or syscall fault backends in the generic controller;
- a universal target plugin registry;
- remote artifact storage or dashboard services;
- broad normalization/equivalence policies that encode one product domain.

A future change in one of these areas should be justified by a concrete downstream integration and should preserve the current product-vs-infrastructure distinction and reproducibility guarantees.

## Maintenance mode

After this checkpoint, routine work should follow a patrol model:

- fix reproducible correctness bugs;
- fix CI/toolchain regressions;
- tighten an invariant when a downstream integration exposes an ambiguity;
- add a reusable primitive only when at least one real target needs it;
- avoid speculative feature expansion when the existing substrate already expresses the required test.

In short: keep the correctness core boring, deterministic, and reusable. Product complexity belongs above it.


## Domain-adapter phase promotion

The generic correctness substrate remains at the stable boundary above. The next active
architecture phase is target-specific composition above that core, beginning with a
bounded two-connection SQLite scenario executor.

This promotion addresses an observed integration pattern: reader and writer semantics
were increasingly represented by one fixed worker per scenario. The new adapter keeps
the core harness unchanged while moving reusable connection ordering into a strict,
budgeted data-plane program. Its first acceptance evidence covers WAL snapshot visibility
and writer exclusion across DELETE and WAL journal modes with real process and database
execution.

Specialized crash, backup, checkpoint, and multi-process workers are not deprecated by
this promotion. They remain authoritative where the two-connection program cannot
express the same failure boundary without weakening evidence.


### Two-connection consolidation checkpoint

The bounded scenario executor now owns recognized SQLite busy outcomes for begin,
non-query, and query operations. This makes stale-reader SQLITE_BUSY_SNAPSHOT and
DELETE-vs-WAL reader contention executable through the same strict data-plane protocol.

The former fixed WAL snapshot, WAL busy-snapshot, and reader-contention workers are
retired after equivalent real-process regressions moved onto the generic executor.
This is an architecture consolidation, not a reduction in evidence: the semantic
assertions remain executable while duplicate temporary-database and connection
orchestration is removed.

Crash recovery, online backup, checkpoint, reader-process, writer-process, and
durability targets remain specialized because their process or failure boundaries are
outside the two-connection executor's contract.


### Two-connection structured triage checkpoint

After consolidating simple reader/writer scenarios into the bounded executor, the next
architecture layer is failure minimization rather than additional fixed workers. The
two-connection adapter now mirrors the mature query/transaction path with deterministic
step deletion, setup deletion, scalar parameter simplification, stable-signature
preservation, bounded reducer work, repro publication, and replay.

The generic reducer and harness remain unchanged. SQLite request shape and concurrency
semantics stay in target-specific modules above the stable core. Real DELETE-vs-WAL
reader-contention evidence proves the vertical path from process execution through
structured reduction to minimized reproducible evidence.


### Two-connection discovery checkpoint

The two-connection SQLite adapter has now progressed from executable scenarios and
structured triage to bounded discovery. Valid scenario seeds can be mutated
deterministically across begin-mode and scalar-parameter dimensions, while a
target-specific feedback evaluator extracts only finite transcript structure.

A real DELETE-vs-WAL campaign proves discovery rather than fixture enumeration: an
IMMEDIATE seed matches, the deterministic EXCLUSIVE mutation exposes the journal-mode
reader-contention difference, and the feedback campaign retains that product mismatch.
The generic fuzz scheduler, feedback corpus policy, differential harness, and reducer
remain unchanged; SQLite concurrency semantics stay above the stable core.
