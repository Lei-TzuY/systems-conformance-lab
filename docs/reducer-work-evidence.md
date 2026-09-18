# Reducer work evidence

`reduce_case` exposes deterministic work accounting for successful reduction runs so callers can persist and compare reducer behavior without inferring completion semantics from counters.

A `ReductionResult` records `evaluations`, `candidate_visits`, `accepted_steps`, `exhausted_budget`, and `termination_reason`. `termination_reason` is derived by the frozen result itself and is included by dataclass serialization:

- `fixed_point` means the deterministic candidate schedule completed without accepting another strictly smaller failure-preserving case.
- `evaluation_budget` means the failure-predicate evaluation ceiling stopped the run before a fixed point was established.

Candidate-enumeration exhaustion remains a separate infrastructure failure. It raises `CandidateBudgetExhausted` with `candidate_visits` and `max_candidate_visits`; it is not converted into a successful `ReductionResult` or a product-level non-reproduction.

This distinction lets triage and repro tooling retain the exact reason a minimized case was returned. A case produced at an evaluation ceiling can therefore be treated as a bounded intermediate result rather than being mistaken for a proven local fixed point.

## Persisted triage evidence

`reduce_failure_to_repro` persists the successful reduction work record in the repro bundle metadata under the reserved `systems_conformance_reduction` key. The record uses schema version `systems-conformance.reduction-evidence.v1` and contains only `evaluations`, `candidate_visits`, `accepted_steps`, `exhausted_budget`, and `termination_reason`; reduced case bytes remain exclusively in `input.bin`.

Caller metadata may not override the reserved key. This keeps the persisted work record bound to the reduction that actually produced the repro instead of allowing user-supplied metadata to spoof reducer evidence. Normal repro loading and replay preserve the namespaced record, so offline triage can distinguish a proven fixed point from an evaluation-budget intermediate result after the in-memory `ReductionResult` is gone.
