# Process byte budgets

The process runner and differential harness use the same byte-budget contract.

`max_input_bytes` and `max_output_bytes` are non-negative integers. `max_total_output_bytes` is a positive integer. Boolean and floating-point values are rejected rather than coerced.

The runner validates these values before launching a target. The harness validates them at construction time so its replay-context fingerprint uses the same types that execution accepts. Zero remains valid for input and per-stream capture limits; the aggregate emitted-output budget remains strictly positive.