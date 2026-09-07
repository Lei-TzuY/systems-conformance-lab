# SQLite transaction JSON depth budget

`SQLiteTransactionTarget` treats every test case as untrusted protocol input. Its `max_json_depth` setting adds a deterministic structural ceiling before the worker calls Python's JSON decoder, so malformed deeply nested documents cannot consume an implementation-dependent parser recursion budget first.

The default is `32`. The value must be a positive integer and is encoded directly in the target argv, which means the existing `DifferentialHarness` replay-context fingerprint distinguishes targets configured with different JSON-depth ceilings.

The preflight scans the exact stdin bytes and counts only structural `{`, `[`, `}`, and `]` delimiters that occur outside JSON strings. Delimiter-looking bytes inside strings and escaped quotes do not affect the count. Once opening-object/array nesting would exceed the configured ceiling, the target exits deterministically with code `2` and a `protocol_error: request exceeds max_json_depth: N` diagnostic before `json.loads`, SQLite connection creation, or SQL preparation.

This is deliberately adapter-local rather than a generic JSON parser abstraction. The transaction protocol itself remains shallow and still performs its existing strict shape, scalar-parameter, statement-count, SQL-byte, fault-specification, and SQLite VM-budget validation after parsing.

```python
from systems_conformance import SQLiteTransactionTarget

bounded = SQLiteTransactionTarget(max_json_depth=8).as_command_target()
```

Real-process integration coverage verifies three boundaries: a deeply nested malformed request is rejected before JSON parsing, a valid request at the exact structural depth executes successfully, and `DifferentialHarness` observes different depth configurations through the normal candidate/oracle process path and stable failure classification.
