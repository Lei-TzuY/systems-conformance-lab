# SQLite query parameter fuzzing

`SQLiteQueryParameterMutations` is an adapter-specific deterministic case source for the SQLite query target. It keeps the generic fuzz scheduler free of SQL semantics while avoiding low-value JSON protocol corruption.

## Schedule

The corpus is finite and index-addressable. Exact seed bytes are emitted first. Generated cases then walk query parameters in index order. Each JSON scalar receives deterministic same-type boundary values and selected cross-type values; query text and setup statements are preserved.

If a valid query fault is present, the schedule then probes occurrence checkpoints `0`, `1`, and `2` while preserving the fault operation and `abort` kind. This makes unreachable fault seeds useful for discovering early deterministic checkpoints without changing fault identity.

Generated duplicates and cases above `max_case_bytes` are skipped. Seeds themselves must fit the bound and must be strict UTF-8 JSON objects with a string `query`, string-only `setup`, scalar `params`, and a valid optional query fault.

## Conformance use

The corpus is intended for `run_fuzz_campaign` or feedback/discovery orchestration with a real `SQLiteQueryTarget` differential harness. A useful campaign starts from a protocol-valid case that currently matches, then lets scalar or occurrence mutations expose a semantic, resource-contract, or fault-model difference. Failures remain ordinary differential results: target protocol/resource differences are product failures, while process-launch or harness failures remain infrastructure failures.
