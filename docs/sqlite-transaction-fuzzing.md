# SQLite transaction parameter fuzzing

`SQLiteTransactionParameterMutations` is an adapter-specific deterministic case source for the SQLite transaction target. It keeps the generic fuzz scheduler free of SQL semantics while avoiding the low-value protocol corruption produced by arbitrary byte mutation of JSON requests.

## Schedule

The corpus is finite and index-addressable. Exact seed bytes are emitted first. Generated cases then walk, in order:

1. seed order;
2. transaction statement order;
3. parameter order;
4. a small deterministic replacement schedule for that JSON scalar type.

Integer parameters use `0`, `1`, and `-1` excluding the original value. Finite floats use the corresponding floating-point values, strings use `""`, `"0"`, and `"x"`, booleans flip value, and null is replaced by `0` and `""`. Duplicate cases are removed without changing first-witness order.

The source validates unique JSON object fields, rejects non-finite constants and unsupported parameter values, requires a non-empty transaction list, and enforces `max_case_bytes` on both seeds and generated cases. It changes only transaction parameter values; setup SQL, statement SQL, observation, fault specification, and other request fields stay unchanged.

## Real target validation

The integration regression starts from a foreign-key-valid request that matches under both `foreign_keys=True` and `foreign_keys=False`. The first integer mutation changes the child reference from `1` to `0`. The enforcing target then reports a SQLite constraint failure while the non-enforcing target commits successfully, so `run_fuzz_campaign` discovers a real `product_mismatch` on the second evaluation without any infrastructure failure.

Use `corpus.case_count` as the fuzz evaluation budget when the complete schedule should be replayed. Because the schedule contains no RNG or shared mutable state, a failing evaluation index identifies the same case across runs for the same seeds and implementation version.
