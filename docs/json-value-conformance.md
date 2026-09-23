# Cross-runtime JSON value conformance

This phase adds a third non-storage interoperability domain above the stable process and
differential substrate: native JSON value materialization in Python and Node.

The target boundary is intentionally narrower than “all JSON behavior.” Each real child
process receives one bounded raw byte string on stdin, decodes it as strict UTF-8, parses
one JSON text with the runtime's native parser, and projects the resulting value onto the
same tagged observation tree.

## Runtime targets

- `JSONValueTarget` executes Python's standard-library `json.loads`.
- `JSONNodeValueTarget` executes Node 22 `JSON.parse`.
- Python implementation/version and Node version are captured at target construction,
  verified before semantic input is consumed, and therefore participate in replay
  identity through immutable command configuration.

No parser is reimplemented in shared infrastructure and neither runtime is normalized to
the other's numeric policy.

## Observation model

Successful values are represented as tagged nodes:

- null: `["null"]`
- boolean: `["bool", value]`
- number: `["number", native_numeric_text]`
- string: `["string", value]`
- array: `["array", children]`
- object: `["object", [[key, value], ...]]`

Object keys are observed in a language-neutral deterministic order based on their
ASCII-escaped JSON string representation. This deliberately removes host object-property
iteration order from the comparison so numeric materialization remains independently
visible. Duplicate object names retain each native parser's resulting value; the initial
textual duplicate sequence itself is not preserved after parsing.

Structural projection is bounded by maximum depth and node count. Input bytes have an
independent target ceiling in addition to the generic harness stdin limit. Python
parse-time recursion exhaustion for already-out-of-scope deep values is classified at
the same value-budget boundary rather than misreported as a syntax difference. Budget
exhaustion is a stable target result rather than an unbounded traversal or silent
truncation.

## Executable shared behavior

Integration tests exercise real Python and Node child processes and require matching
observations for:

- null, booleans, strings, integer values, arrays, and objects;
- duplicate object names where both native parsers retain the last value;
- canonicalized observation of integer-like object keys despite different host property
  enumeration rules;
- numeric overflow such as `1e400` where both runtimes materialize positive infinity;
- escaped lone surrogate string data without relying on host stdout encoding;
- invalid UTF-8 rejection before JSON parsing;
- shared syntax errors such as trailing commas, single-quoted objects, trailing text, and
  a leading UTF-8 BOM under this explicit decode boundary;
- deterministic depth, node-count, and byte-budget failure.

## Preserved native divergences

The value projection intentionally preserves runtime numeric semantics rather than
coercing both implementations to arbitrary precision or IEEE-754:

- Python preserves an integer beyond JavaScript's safe-integer range while Node rounds it
  when materializing a `Number`;
- Python preserves float spelling for values such as `1.0` and `-0.0`, while Node's
  numeric stringification collapses them to `1` and `0`;
- Python's standard `json.loads` accepts the non-standard constants `NaN`, `Infinity`,
  and `-Infinity`, while `JSON.parse` rejects them.

A deterministic discovery campaign starts from a matching JSON document, reaches the
large-integer precision witness, publishes a context-bound repro, and replays the same
stable product-mismatch signature through the unchanged generic harness.

## Scope boundary

This checkpoint does not claim RFC 8259 parser conformance as a whole, JSON5 support,
streaming/text-sequence parsing, serializer byte-for-byte equivalence, source-position or
error-message equivalence, duplicate-key diagnostics, JSON Schema, canonical JSON
standards, reviver/object-hook behavior, arbitrary-precision normalization, or browser
JavaScript behavior beyond the Node runtime target. Those require separate executable
contracts rather than being folded into this value-semantic boundary.
