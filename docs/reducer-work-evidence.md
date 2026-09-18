# Reducer work evidence

`reduce_case` exposes deterministic work accounting for successful reduction runs so callers can persist and compare reducer behavior without inferring completion semantics from counters.

A `ReductionResult` records `evaluations`, `candidate_visits`, `accepted_steps`, `exhausted_budget`, and `termination_reason`. `termination_reason` is derived by the frozen result itself and is included by dataclass serialization:

- `fixed_point` means the deterministic candidate schedule completed without accepting another strictly smaller failure-preserving case.
- `evaluation_budget` means the failure-predicate evaluation ceiling stopped the run before a fixed point was established.

Candidate-enumeration exhaustion remains a separate infrastructure failure. It raises `CandidateBudgetExhausted` with `candidate_visits` and `max_candidate_visits`; it is not converted into a successful `ReductionResult` or a product-level non-reproduction.

This distinction lets triage and repro tooling retain the exact reason a minimized case was returned. A case produced at an evaluation ceiling can therefore be treated as a bounded intermediate result rather than being mistaken for a proven local fixed point.
