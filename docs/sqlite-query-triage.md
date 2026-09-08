# SQLite query multi-phase triage

`reduce_sqlite_query_failure_to_repro` turns one stable `SQLiteQueryTarget` fuzz witness into a structured reduced repro without changing the captured failure identity.

The phases run in this order:

1. reduce a configured SQLite fault occurrence toward earlier deterministic checkpoints;
2. delete setup statements with the existing coarse-to-fine setup reducer;
3. simplify scalar query parameters after the setup shape stabilizes;
4. publish the reduced case through `DifferentialHarness.write_repro`, which re-executes the final input against the exact expected failure signature before writing evidence.

Every candidate is checked with `DifferentialHarness.preserves_failure`. A reduction that changes a `product_mismatch` into another mismatch dimension, an infrastructure failure, or a passing comparison is rejected. The triage path does not rewrite SQL or infer dependencies between setup statements and the query; SQLite execution remains the semantic oracle for candidate validity.

The focused real-target test uses process-isolated SQLite candidate and oracle workers with deterministic setup fault injection. It verifies that fault occurrence, setup cardinality, and scalar parameter complexity all decrease while the same stable failure signature survives, then replays the emitted repro bundle to prove the artifact is executable evidence rather than a reducer-only result.
