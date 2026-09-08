# Process timeout contract

`run_process` and `DifferentialHarness` accept a finite positive integer or floating-point timeout in seconds. Python booleans are rejected even though `bool` is an `int` subclass, and non-numeric values are rejected rather than coerced.

Timeout validation happens before target launch. This keeps caller configuration errors out of the untrusted execution path and prevents values such as `True` from silently becoming a one-second process budget or entering replay-context fingerprints as if they were intentional numeric limits.

Zero, negative values, NaN, and infinities remain invalid. Positive integers and finite positive floats remain valid and execute through the normal process-isolated target path.
