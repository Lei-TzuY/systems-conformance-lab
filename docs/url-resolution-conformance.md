# HTTP relative URL resolution interoperability

This phase extends the HTTP URL parser domain from parsing one already-absolute URL into
resolving a reference against an absolute base. Python urllib.parse.urljoin/urlsplit and
Node 22 WHATWG URL execute as separate child-process targets above the unchanged runner,
differential harness, failure discovery, repro, and replay substrate.

## Binary request protocol

stdin is language-neutral binary framing rather than JSON:

1. four unsigned big-endian bytes containing the base URL byte length;
2. exactly that many base URL bytes;
3. all remaining bytes as the reference.

The framing is rejected if it is shorter than four bytes or the declared base length
exceeds the remaining payload. Base and reference are decoded independently as strict
UTF-8. Invalid framing emits request_error; invalid UTF-8 emits unicode_decode_error.

The base must itself be an absolute HTTP/HTTPS URL with a non-empty hostname. The
resolved result must remain in the same HTTP/HTTPS scope. Successful resolution is
projected onto the parser domain's bounded canonical record: scheme, credentials,
hostname/port, path, query, and fragment.

## Shared semantics and native divergence

Executable shared-subset evidence covers:

- parent and same-directory references;
- query-only and fragment-only references;
- network-path references;
- absolute references overriding the base.

Native policy is deliberately preserved rather than normalized away. WHATWG special-URL
backslash handling differs from urllib.parse during relative resolution, an empty
reference against a base containing a fragment exposes different native behavior, and
WHATWG special-scheme slash recovery can normalize a base such as
`https:///missing-host` that urllib.parse rejects for lacking a hostname. These remain
product mismatches rather than being hidden by adapter policy.

A deterministic two-case discovery schedule begins with a matching parent reference and
then a backslash reference that produces a stable product mismatch. The unchanged
discovery campaign retains the witness, the existing harness publishes a context-bound
repro, and replay reproduces the same stable failure signature.

## Runtime semantic identity

Python implementation/version and Node process.version are captured at target
construction, embedded in immutable process configuration, and verified before stdin is
consumed. The normal replay-context fingerprint therefore changes across runtime parser
upgrades without adding URL-specific state to the generic core.

## Scope boundary

This phase does not claim all WHATWG relative-resolution behavior, IDNA/UTS #46,
file URLs, opaque URLs, browser origin/security policy, form encoding, URLSearchParams
ordering, or percent-encoding normalization. Those remain separate interoperability
surfaces.
