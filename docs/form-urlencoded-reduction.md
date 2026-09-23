# application/x-www-form-urlencoded encode reduction

The encode-side interoperability target uses a binary ordered-pair frame rather than
JSON. `form_urlencoded_encode_reduction_candidates` provides a domain-aware reducer for
that protocol so discovered serialization mismatches can be minimized without corrupting
pair boundaries, duplicate-key ordering, UTF-8 fields, or length framing.

The reducer fails closed on truncated framing, impossible pair counts, trailing bytes,
and invalid UTF-8. It never repairs malformed input. For a valid frame it deterministically
tries whole-pair deletion, then key and value reductions. Every candidate is unique,
strictly smaller in encoded bytes, and is rebuilt from semantic fields so all count and
length prefixes remain internally consistent.

Executable integration coverage starts with the real Python `urllib.parse.urlencode`
and Node WHATWG `URLSearchParams` targets. A padded witness containing `~` exercises
their native percent-encoding policy divergence, passes through failure discovery and
`reduce_failure_to_repro`, and replays the reduced repro with the same stable
`product_mismatch` signature. This keeps reduction evidence attached to real target
behavior rather than a synthetic reducer predicate.

This reducer intentionally covers encode-mode ordered-pair frames only. Decode mode has
raw form-body syntax and percent-decoding policy, so it requires a separate syntax-aware
contract rather than reusing binary-frame reductions.
