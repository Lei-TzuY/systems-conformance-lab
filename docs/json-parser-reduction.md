# JSON parser structural reduction

`json_reduction_candidates` provides a deterministic domain-aware reducer for the
Python/Node JSON parser interoperability target. It parses only strict UTF-8 and
standards-compliant JSON, then emits complete JSON documents that are strictly smaller
than the input. Malformed UTF-8, malformed JSON, and non-standard constants such as
`NaN` fail closed instead of being repaired by reducer infrastructure. Structural nesting
beyond 256 levels is rejected before any candidate is emitted, keeping the recursive
candidate walk below its explicit safety boundary rather than leaking `RecursionError`.

Candidate order is stable: canonical whitespace/key serialization first when it is a
strict reduction, followed by object-member deletion, key shrinking, recursive value
reduction, array-element deletion, and scalar shrinking. Duplicate candidates are
suppressed. Every emitted case is measured by encoded byte length and must be strictly
smaller than its parent input.

The integration test drives the real Node `JSON.parse` and Python `json.loads` process
targets through `DifferentialHarness`. A padded integer-precision divergence is reduced
to a smaller JSON document and published through `reduce_failure_to_repro`; replay must
preserve the original `product_mismatch` signature. This verifies executable reduction
and repro interoperability rather than a reducer-only fixture.
