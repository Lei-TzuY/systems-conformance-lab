# SQLite query JSON depth budget

`SQLiteQueryTarget` treats each request as untrusted protocol input. Its `max_json_depth` setting adds a deterministic structural ceiling before Python's JSON decoder runs, matching the resource-safety boundary already used by the transaction target.

The default is `32`. The value must be a positive integer and is encoded directly in target argv, so `DifferentialHarness` replay context distinguishes targets configured with different depth ceilings.

The preflight scans exact stdin bytes and counts `{` and `[` nesting only outside JSON strings. Delimiter-looking bytes inside strings and escaped quotes do not consume the budget. If nesting would exceed the configured ceiling, the worker exits with code `2` and `protocol_error: request exceeds max_json_depth: N` before `json.loads`, SQLite connection creation, or SQL preparation.

This remains an adapter-local protocol bound. Existing UTF-8, duplicate-field, scalar-parameter, SQL-byte, fault, SQLite VM, wall-clock, stdin, and output limits continue to apply independently.

Real-process integration coverage verifies a deeply nested malformed request is rejected deterministically, string contents do not create false structural depth, and two real SQLite query targets with different depth budgets produce a stable `product_mismatch` through `DifferentialHarness` when the same otherwise-valid request crosses only one configured boundary.
