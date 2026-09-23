# HTTP URL parser interoperability

This domain promotes the conformance lab beyond database behavior and Unicode codec
services into a structured protocol parser. Python urllib.parse and Node 22 WHATWG URL
run as separate child-process targets above the unchanged process runner, differential
harness, failure discovery, repro, and replay substrate.

stdin is the exact URL byte sequence. Both targets decode strict UTF-8 first, accept only
absolute http/https URLs with a non-empty hostname, and project successful parses onto a
bounded canonical record:

- scheme;
- username and password;
- hostname and port;
- path;
- query;
- fragment.

Decode rejection and out-of-scope/parse rejection use stable JSON error records. Native
exception text and parser-specific error classes are not part of the comparison surface.

## Shared conformance and deliberate divergence

The executable suite first proves a common subset: ordinary absolute HTTP/HTTPS URLs,
explicit non-default ports, percent-encoded path/query bytes, and ASCII host case
normalization must produce identical canonical output.

The same targets then intentionally preserve native parser policy instead of normalizing
one implementation toward the other. Stable WHATWG-vs-urllib differences therefore
appear as real product mismatches. Initial evidence covers:

- WHATWG dot-segment removal versus urllib.parse path preservation;
- WHATWG default-port elision versus urllib.parse explicit port reporting;
- WHATWG special-URL backslash handling versus urllib.parse netloc/path handling.

A deterministic two-case discovery schedule begins with one matching URL and then one
dot-segment divergence. The generic discovery campaign retains that stable failure
witness; the unchanged harness writes a context-bound repro and replay reproduces the
same failure signature.

## Runtime semantic identity

URL parsing policy can change across runtime releases even when logical target settings
do not. The Python target therefore binds implementation and Python version into argv
and verifies both before consuming stdin. The Node target probes process.version through
the bounded runner, embeds the captured value into its immutable script, and verifies it
before reading stdin. The existing replay-context fingerprint therefore detects runtime
drift without adding parser policy to the generic core.

## Scope boundary

This phase does not claim equivalence for all WHATWG URL behavior, IDNA/UTS #46,
IPvFuture, file URLs, relative resolution against a base URL, form encoding, URLSearchParams
ordering, percent-encoding normalization, or browser origin/security policy. Those are
separate parser/interoperability surfaces.
