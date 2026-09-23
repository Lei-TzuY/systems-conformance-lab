# Multipart form-data structural reduction

The multipart/form-data interoperability target has a domain-aware reducer for stable differential failures. The reducer operates on the same fixed, target-owned boundary used by the Python and Node adapters and only accepts the canonical CRLF framing emitted by the conformance corpus.

Reduction is intentionally fail-closed. Inputs with a preamble or epilogue, LF-only framing, malformed or non-ASCII header lines, a missing closing boundary, or ambiguous/non-canonical boundary framing are rejected rather than repaired. This prevents reduction from changing parser policy while searching for a smaller witness.

For canonical inputs the reducer can remove complete parts and shrink part bodies. It does not mutate headers, so Content-Disposition and Content-Type semantics that trigger native runtime differences remain part of the witness. Every emitted candidate is deterministic, unique, and strictly smaller in encoded bytes.

The integration test validates the reducer against the real Python stdlib multipart path and Node `Response.formData()` target. A padded `charset=iso-8859-1` witness is discovered as a product mismatch, reduced while preserving its stable failure signature, written as a repro bundle, and replayed through the normal differential harness.
