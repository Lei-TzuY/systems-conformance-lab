# Stateful URLSearchParams interoperability

This phase promotes the URL domain from stateless form encode/decode and one-shot full
URL query canonicalization into ordered state mutation. Python and Node execute as
separate child-process targets above the unchanged runner, comparator, discovery, repro,
and replay substrate.

The Node target uses the native WHATWG URLSearchParams API. Python uses an ordered list
of Unicode string pairs plus urllib.parse.urlencode and deliberately retains Python's
native Unicode string ordering for sort rather than emulating WHATWG UTF-16 code-unit
ordering.

## Binary request protocol

stdin is a language-neutral binary frame:

1. four-byte big-endian initial pair count;
2. for each pair: four-byte key length, key UTF-8 bytes, four-byte value length, value
   UTF-8 bytes;
3. four-byte big-endian operation count;
4. ordered operations:
   - opcode 1 append: key field plus value field;
   - opcode 2 set: key field plus value field;
   - opcode 3 delete: key field;
   - opcode 4 sort: no fields;
5. no trailing bytes.

The targets independently bound initial pair count, operation count, and field byte
length. These ceilings are immutable target configuration and participate in replay
identity. Malformed framing or unknown opcodes produce request_error; invalid field
UTF-8 produces unicode_decode_error. The entire raw request remains additionally bounded
by the generic harness input ceiling.

## Executable evidence

The shared subset proves stateful ordered-pair behavior for append, set, delete, stable
ASCII sort, duplicate-key position semantics, and post-mutation serialization.

The phase also preserves a real ordering-policy difference rather than normalizing it
away. WHATWG URLSearchParams.sort orders names by UTF-16 code units. Python's normal
Unicode string ordering compares code points. A supplementary-plane key such as U+1F600
therefore sorts before U+E000 in Node because the leading surrogate is below E000,
while Python places U+E000 first because E000 is below 1F600 as a code point.

A deterministic two-case discovery schedule first sorts ordinary ASCII keys and then
sorts the supplementary/BMP pair. The generic discovery campaign retains the stable
stdout mismatch, the existing harness publishes the exact binary request as a
context-bound repro, and replay reproduces the same failure signature.

## Runtime identity and architecture boundary

Python implementation/version and Node process.version are captured at target
construction and verified before semantic input is processed. Structural ceilings are
embedded in argv or the immutable Node script. Runtime and protocol configuration
therefore flow into the existing replay-context fingerprint without changing generic
infrastructure.

This phase does not claim browser-live URL/searchParams object coupling, iterator
mutation during traversal, two-argument delete/has extensions, non-UTF-8 form encodings,
multipart forms, browser navigation/submission policy, or arbitrary WHATWG URL parser
equivalence. Those remain separate interoperability surfaces.
