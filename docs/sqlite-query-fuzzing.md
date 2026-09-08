# SQLite query parameter fuzzing

`SQLiteQueryParameterMutations` is an adapter-specific deterministic case source for the SQLite query target. It keeps the generic fuzz scheduler free of SQL semantics while avoiding low-value JSON protocol corruption.

## Schedule

The corpus is finite and index-addressable. Exact seed bytes are emitted first. Generated cases then walk query parameters in index order. Each JSON scalar receives deterministic same-type boundary values and selected cross-type values; query text and setup statements are preserved.

If a valid query fault is present, the schedule then probes occurrence checkpoints `0`, `1`, and `2` while preserving the fault operation and `abort` kind. This makes unreachable fault seeds useful for discovering early deterministic checkpoints without changing fault identity.

Generated duplicates and cases above `max_case_bytes` are skipped. Seeds themselves must fit the bound and must be strict UTF-8 JSON objects with a string `query`, string-only `setup`, scalar `params`, and a valid optional query fault.

## Semantic feedback

`SQLiteQueryFeedbackEvaluator` adapts a real `DifferentialHarness` execution to the generic `run_feedback_guided_campaign` contract. Its feedback vocabulary is deliberately structural and bounded: comparison class/mismatch fields, exit/signal/timeout/infrastructure classes, stream truncation, recognized deterministic stderr categories, and successful SQLite result shape.

Successful result feedback records bucketed column, row, and row-width counts plus normalized value kinds (`null`, `bool`, `int`, `float`, `text`, and `blob`). It never includes SQL text, column names, raw result values, raw stderr, timings, or output hashes. This prevents corpus growth from treating every distinct query value as synthetic coverage while still retaining cases that reach materially different execution/result classes.

Malformed successful stdout is represented by stable invalid-JSON/shape feature classes rather than raising from the feedback layer. Process/harness failures remain ordinary differential infrastructure failures; feedback does not reclassify them.

## Conformance use

The deterministic mutation corpus can be used with `run_fuzz_campaign`, failure discovery, or feedback-guided orchestration against a real `SQLiteQueryTarget` differential harness. A useful campaign starts from a protocol-valid case that currently matches, then lets scalar or occurrence mutations expose a semantic, resource-contract, or fault-model difference. `SQLiteQueryFeedbackEvaluator` lets the feedback-guided scheduler retain only cases that add new structural execution/result features while independently preserving stable failure witnesses.

Failures remain ordinary differential results: target protocol/resource differences are product failures, while process-launch or harness failures remain infrastructure failures. Adapter-specific structured reducers can then minimize retained SQLite query witnesses without changing the generic fuzz engine.
