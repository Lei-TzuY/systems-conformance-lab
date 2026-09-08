# SQLite transaction parameter fuzzing

`SQLiteTransactionParameterMutations` is an adapter-specific deterministic case source for the SQLite transaction target. It keeps the generic fuzz scheduler free of SQL semantics while avoiding the low-value protocol corruption produced by arbitrary byte mutation of JSON requests.

## Schedule

The corpus is finite and index-addressable. Exact seed bytes are emitted first. Generated cases then walk, in order:

1. seed order;
2. transaction statement order;
3. transaction parameter order;
4. observation parameter order;
5. a bounded deterministic replacement schedule for that JSON scalar type.

The replacement schedule keeps same-type boundary values first, then selected cross-type scalar values. Integer parameters use `0`, `1`, and `-1` before `null`, the corresponding finite float, the decimal string form, and `"x"` (excluding the original value). Finite floats use `0.0`, `1.0`, and `-1.0` before `null` and string probes. Strings use `""`, `"0"`, and `"x"` before `null`, `0`, and `1`. Booleans flip value before `null`, integer, and string probes; null uses `0`, `""`, and `false`. JSON scalar identity is type-sensitive, so `true`, `1`, and `1.0` remain distinct mutations even though Python equality would otherwise collapse them. Duplicate encoded cases are removed without changing first-witness order.

The source validates unique JSON object fields, rejects non-finite constants and unsupported parameter values, requires a non-empty transaction list plus an observation object, and enforces `max_case_bytes` on both seeds and generated cases. It changes only transaction or observation parameter values; setup SQL, statement SQL, fault specification, and other request fields stay unchanged.

## Semantic feedback

`SQLiteTransactionFeedbackEvaluator` adapts a real `DifferentialHarness` execution to the generic `run_feedback_guided_campaign` contract. Its feedback vocabulary is deliberately structural and bounded: comparison class and mismatch fields, exit/signal/timeout/infrastructure classes, stream truncation, recognized deterministic stderr categories, transaction statement-count buckets, and normalized transaction/observation result-shape buckets.

Successful transcript feedback never embeds SQL text, column names, raw result values, stderr text, timings, or output bytes. Transaction statement result features are position-independent: the evaluator records the structural classes observed anywhere in the transaction transcript rather than generating a separate feature namespace for every statement index. This keeps corpus admission stable when a reducer removes or reorders unrelated statements while still distinguishing result cardinality, row width, and normalized SQLite value kinds.

Malformed or truncated successful output is represented by bounded shape/error features instead of being parsed into unbounded strings. Non-zero exits use only the stable stderr prefixes `protocol_error`, `sqlite_error`, `result_error`, `sqlite_vm_budget_exceeded`, and `injected_fault` when present; all other stderr collapses to `other`.

The evaluator can be paired directly with `SQLiteTransactionParameterMutations` so the generic feedback scheduler retains only mutations that add structural transaction coverage while independently preserving stable failure witnesses.

## Real target validation

The integration regression starts from a foreign-key-valid request whose parent table contains integer keys `-1`, `0`, and `1`. Same-type integer mutations, `null`, `1.0`, and `"1"` all still match between `foreign_keys=True` and `foreign_keys=False`. Only the later cross-type probe `"x"` makes the enforcing target report a foreign-key constraint failure while the non-enforcing target commits successfully. `run_fuzz_campaign` therefore discovers a real `product_mismatch` that the previous same-type-only schedule could not reach, with no infrastructure failure.

A second integration keeps transaction input fixed and mutates only an observation filter. That campaign demonstrates that parameter fuzzing can reveal a commit-vs-rollback state difference through a valid post-finalization query rather than by corrupting the request protocol.

The semantic-feedback integration uses two real process-isolated transaction targets with different `max_result_rows` budgets. The seed transaction returns one row and matches. A deterministic parameter mutation expands the transaction SELECT to two rows, so the bounded candidate reports `result_error` while the oracle succeeds. The feedback-guided campaign must admit both the successful one-row transcript feature and the later error/product-mismatch features without classifying either child as an infrastructure failure.

Use `corpus.case_count` as the fuzz evaluation budget when the complete schedule should be replayed. Because the schedule contains no RNG or shared mutable state, a failing evaluation index identifies the same case across runs for the same seeds and implementation version.
