# SQLite query aggregate result byte budget

`SQLiteQueryTarget` treats cumulative result materialization as a separate resource dimension from row count and per-value size. A query can return many individually small values that stay below both `max_result_rows` and `max_result_value_bytes` while still forcing the child process to accumulate a large normalized result before final JSON serialization.

`SQLiteQueryTarget(max_result_bytes=N)` therefore requires a positive integer and encodes the value in worker argv/replay identity. The default is 512 KiB.

The budget measures the UTF-8 byte length of the compact JSON representation of the `rows` array, including row/value separators and array delimiters. Values are normalized through the existing deterministic SQLite result contract before they are charged. The exact boundary is accepted; the first value that would make the rows payload exceed the budget exits deterministically with code `4` and:

```text
result_error: result exceeds max_result_bytes: N
```

The check runs while consuming the SQLite cursor, before the complete result is serialized. It complements rather than replaces:

- `max_result_rows`, which bounds result cardinality;
- `max_result_value_bytes`, which bounds each TEXT/BLOB before JSON or hexadecimal expansion;
- the shared process output ceilings, which remain the final transport-level protection.

A focused boundary test verifies that `[[1],[2]]` is accepted at its exact nine-byte compact JSON size and rejected at eight bytes. A real `DifferentialHarness` integration runs the same SQLite query against targets with eight- and nine-byte budgets and requires a stable `product_mismatch`, demonstrating that the resource ceiling is part of target behavior rather than an infrastructure failure.
