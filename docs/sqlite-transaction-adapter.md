# SQLite transaction transcript target

`SQLiteTransactionTarget` is a process-isolated adapter for one explicit SQLite transaction followed by a post-finalization observation query. It complements `SQLiteQueryTarget`; it does not replace or broaden the single-query protocol.

Each case starts with a fresh in-memory database. Setup statements execute in autocommit mode, then the worker opens exactly one transaction, executes a non-empty ordered list of statement objects, applies the target's configured `commit` or `rollback` finalization, and finally executes an observation statement. The emitted JSON contains the canonical columns/rows for every transaction step plus the post-finalization observation. BLOBs use the same `{"$blob":"hex"}` representation as the query adapter.

```python
from systems_conformance import SQLiteTransactionTarget

commit_target = SQLiteTransactionTarget(finalize="commit").as_command_target()
rollback_target = SQLiteTransactionTarget(finalize="rollback").as_command_target()
fault_target = SQLiteTransactionTarget(enable_faults=True).as_command_target()
```

The strict input shape is:

```json
{
  "setup": ["CREATE TABLE items(v INTEGER)"],
  "transaction": [
    {"sql": "INSERT INTO items VALUES (?)", "params": [42]}
  ],
  "observe": {"sql": "SELECT v FROM items ORDER BY v", "params": []},
  "fault": {"operation": "finalize", "occurrence": 0, "kind": "abort"}
}
```

`fault` is optional. When `enable_faults=True`, the worker maps it onto the shared `FaultSpec` / `FaultController` substrate. Supported logical operations are `setup`, `transaction`, `finalize`, and `observe`; occurrences are zero-based within the selected operation. The only current transaction fault kind is `abort`, which exits deterministically with code 5 and a stable `injected_fault` diagnostic before the selected logical operation runs. When faults are disabled the same request executes normally. Fault enablement is encoded in target argv, so the existing replay-context fingerprint distinguishes fault-enabled and fault-disabled targets.

Input-provided transaction control is denied by SQLite's authorizer so a case cannot bypass the configured finalization policy. `ATTACH`, `DETACH`, input `PRAGMA`, and extension loading are also denied/disabled. Duplicate JSON object fields, unknown fields, non-finite numbers, out-of-range integers, empty transaction programs, invalid fault specifications, and requests exceeding `max_statements` are rejected deterministically. Each statement may bind only JSON scalar values.

`max_statements` is a positive target configuration encoded in argv and therefore in the existing replay-context fingerprint. `max_vm_steps` optionally installs a deterministic SQLite progress-handler budget across setup, transaction, finalization, and observation work. The normal runner timeout, bounded stdout/stderr capture, aggregate output budget, and process-tree cleanup remain required for failures outside SQLite's VM. Injected transaction faults are target observations, not harness infrastructure failures.

The real integration regressions send identical cases through `DifferentialHarness`. One proves commit versus rollback semantics through different post-finalization database state. Another enables a deterministic `finalize` fault only on the candidate while the oracle executes normally; both child processes remain healthy from the runner's perspective and the resulting exit/output difference is classified as a stable `product_mismatch`.
