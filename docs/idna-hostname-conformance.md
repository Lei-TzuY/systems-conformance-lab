# IDNA hostname interoperability

This phase promotes the URL domain from ASCII HTTP parsing/resolution into Unicode
hostname processing. Python's stdlib IDNA2003/Nameprep implementation and Node's WHATWG
domain-to-ASCII behavior execute as separate real child-process targets above the
unchanged process runner, differential harness, discovery, repro, and replay substrate.

stdin is one non-empty hostname encoded as strict UTF-8. Successful processing emits a
bounded semantic record containing the ASCII hostname. Invalid UTF-8 is rejected before
IDNA processing; conversion rejection is represented by a stable idna_error record.
Native exception text and implementation-specific error classes are not compared.

## Shared conformance and deliberate policy divergence

Executable shared-subset evidence includes:

- ordinary lowercase ASCII hostnames;
- Unicode labels such as bücher, mañana, and Japanese example/test labels;
- pre-existing A-label/Punycode input;
- compatibility-width hostname characters;
- Unicode dot-equivalent separators;
- trailing root dot preservation.

The adapters deliberately preserve their native standards policies rather than forcing
one implementation toward the other. Stable differences therefore remain executable
product mismatches. Initial evidence covers:

- German sharp-s: Python IDNA2003 maps ß to ss, while Node preserves the modern label
  distinction and emits xn--fa-hia;
- ZERO WIDTH JOINER: Python Nameprep maps it away while Node rejects the hostname;
- ASCII hostname case: Python's IDNA codec preserves existing ASCII label case while
  Node domain-to-ASCII lowercases it.

A deterministic two-case discovery schedule starts with a shared Unicode label and then
the sharp-s divergence. The generic discovery campaign retains that stable witness; the
unchanged harness publishes a context-bound repro and replay reproduces the same failure
signature.

## Runtime semantic identity

IDNA behavior depends on more than the logical input bytes. Python's stdlib IDNA
implementation is tied to the Python runtime and RFC 3490/3491 Nameprep tables based on
Unicode 3.2. The Python target therefore binds implementation, Python version, and the
Unicode 3.2 table version into argv and verifies them before semantic input processing.

The Node target probes and binds Node, ICU, and Unicode versions through the shared
bounded runner, embeds those values into the immutable child script, and verifies them
before processing stdin. These identities naturally participate in the existing replay
context hash without adding IDNA policy to generic infrastructure.

## Scope boundary

This phase compares native Python IDNA2003 and Node WHATWG hostname processing. It does
not claim universal equivalence between IDNA2003, IDNA2008, and UTS #46, DNS lookup
behavior, resolver policy, certificate hostname verification, public-suffix rules,
browser same-origin policy, or email internationalization. Those remain separate
interoperability/security surfaces.
