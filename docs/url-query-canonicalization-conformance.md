# Full-URL query canonicalization interoperability

This phase connects two previously separate URL-domain boundaries: structured HTTP(S)
URL parsing and application/x-www-form-urlencoded query processing. Python urllib.parse
and Node WHATWG URL/URLSearchParams execute as separate real child processes above the
unchanged runner, differential comparison, discovery, repro, and replay substrate.

Each case is one raw UTF-8 absolute HTTP or HTTPS URL. The adapters first validate the
URL within the shared parser subset, then decode the query into ordered key/value pairs,
re-encode those pairs with the runtime's native form policy, write that canonical query
back into the URL, and serialize the complete URL.

## Executable evidence

The shared subset proves that both runtime pipelines agree on:

- percent-encoded spaces canonicalized to plus;
- duplicate-key order and blank/key-only fields;
- malformed percent triplets treated as literal percent and then re-encoded;
- raw Unicode query values converted to UTF-8 percent encoding;
- literal plus versus encoded plus semantics;
- empty-query removal during full-URL serialization.

The phase also preserves two native policy differences rather than normalizing them
away. URLSearchParams percent-encodes tilde but leaves asterisk unescaped, while Python
urlencode leaves tilde unescaped and percent-encodes asterisk. A full URL containing
`?x=~*` therefore produces a stable stdout mismatch after canonicalization.

Percent-decoded invalid UTF-8 is a second independent policy boundary. Python parse_qsl
with strict UTF-8 returns a canonical form-decode error for `%FF`, while Node
URLSearchParams replacement-decodes it to U+FFFD and serializes `%EF%BF%BD`.
Deterministic discovery schedules publish each divergence as a context-bound repro and
normal replay preserves the original stable failure signature.

Raw malformed UTF-8 is rejected before URL or query processing, and non-HTTP(S) or
relative URL forms reject canonically before query canonicalization.

## Runtime identity and architecture boundary

Python implementation/version are bound into argv and verified before stdin is consumed.
Node process.version is probed through the bounded runner, embedded into the immutable
child script, and verified before stdin processing. These identities participate in the
existing replay-context fingerprint without changing generic infrastructure.

This phase deliberately uses parser inputs whose host/path/port behavior already belongs
to the shared HTTP(S) subset. Known parser differences such as dot-segment removal,
default-port elision, and special-URL backslash handling are not used as query evidence.

The phase does not claim the full mutable URLSearchParams API, sorting semantics, file
or opaque URLs, browser origin/security policy, multipart/form submission, non-UTF-8
forms, or navigation behavior.
