# application/x-www-form-urlencoded interoperability

This phase promotes the URL domain from parsing/resolution/hostname processing into the
ordered key-value serialization boundary used by HTML forms and URLSearchParams.
Python urllib.parse and Node WHATWG URLSearchParams execute as separate real child
processes above the unchanged runner, differential harness, failure discovery, repro,
and replay substrate.

## Language-neutral encode protocol

Encode mode does not use JSON as the case format. stdin is a binary ordered-pair frame:

- four-byte big-endian pair count;
- for each pair, four-byte key length, key UTF-8 bytes, four-byte value length, value
  UTF-8 bytes;
- no trailing bytes.

This preserves duplicate keys and insertion order while keeping transport parsing
independent of either runtime's JSON implementation. The worker validates the complete
frame before serialization and rejects malformed framing canonically. Key/value bytes
use strict UTF-8.

Decode mode consumes raw form-body bytes. The transport bytes must first be strict
UTF-8; only then are plus/percent/form semantics applied. This distinction makes
percent-decoded invalid UTF-8, such as %FF, an observable form-codec policy difference
rather than a raw transport-decoding difference.

## Executable evidence

The shared encode subset covers:

- ordinary ASCII key/value pairs;
- spaces serialized as plus;
- literal plus serialized as %2B;
- UTF-8 percent encoding;
- duplicate-key order;
- empty key/value pairs.

The shared decode subset covers the corresponding forms plus blank values, key-only
fields, malformed percent triplets such as %ZZ, and duplicate-key ordering.

Native serialization policy is preserved rather than normalized away. Python's
quote_plus-based urlencode leaves tilde unescaped and percent-encodes asterisk, while
WHATWG URLSearchParams percent-encodes tilde and leaves asterisk unescaped. Those cases
surface as stable product mismatches.

Decode policy also remains native: Python parse_qsl with strict UTF-8 rejects invalid
percent-decoded byte sequences such as %FF and a truncated multibyte sequence, while
URLSearchParams decodes them with U+FFFD replacement. Deterministic discovery schedules
publish both an encode divergence and a decode divergence as context-bound repros, and
normal replay reproduces their stable stdout mismatch signatures.

## Runtime identity and scope

Mode plus Python implementation/version participate in the Python target argv and are
verified before stdin processing. The Node target probes process.version through the
shared bounded runner, embeds it with mode into the immutable child script, and verifies
it before stdin processing. Those values therefore participate in existing replay
identity without adding form policy to generic infrastructure.

This phase covers string-pair application/x-www-form-urlencoded encode/decode semantics.
It does not claim browser FormData/file upload behavior, multipart/form-data,
URLSearchParams mutation APIs or sorting, query-string integration with full URL objects,
character encodings other than UTF-8, or HTML form submission/navigation policy.
