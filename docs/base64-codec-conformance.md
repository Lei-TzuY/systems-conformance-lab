# Base64/Base64url codec interoperability

This phase promotes the cross-runtime conformance surface into binary-to-text codecs.
Python's standard-library `base64` module and Node's native `Buffer` codec execute as
separate real child processes above the unchanged runner, differential harness, failure
discovery, repro, and replay substrate.

## Executable contract

Encode mode consumes arbitrary stdin bytes and emits one deterministic JSON record with
the runtime-native Base64 or Base64url spelling. Decode mode first requires ASCII
transport bytes, then applies the selected runtime-native decoder and emits decoded bytes
as lowercase hexadecimal. Non-ASCII transport is rejected canonically before codec
semantics so UTF transport policy cannot be mistaken for a Base64 difference.

The target configuration has two bounded dimensions:

- mode: `encode` or `decode`;
- alphabet: `base64` or `base64url`.

The existing harness input/output ceilings bound the byte expansion. Python
implementation/version and Node version are captured at target construction, embedded in
the child configuration, and verified before semantic input processing; normal replay
context therefore rejects runtime drift.

## Shared behavior and preserved native policy

Executable shared evidence covers empty data, canonical padded Base64, complete
unpadded quartets, arbitrary binary bytes, whitespace/ignored-character forgiving
decode cases accepted by both runtimes, and Base64url alphabet bytes.

Native policy is deliberately not normalized away. Node Buffer decoding accepts missing
padding and several malformed/flexible spellings that Python's stdlib decoder rejects.
The deterministic discovery campaign retains a missing-padding witness, writes a
context-bound repro, and replay must preserve the same stdout mismatch signature.

Base64url encode policy also remains native: Node's `base64url` serializer omits
padding, while Python's `urlsafe_b64encode` retains it. Inputs whose encoded length
requires padding therefore surface a stable product mismatch, while complete groups
still match.

## Scope boundary

This checkpoint covers in-memory RFC 4648-style Base64/Base64url byte/string conversion
through the two runtimes' native APIs. It does not claim MIME line wrapping, PEM parsing,
streaming transforms, browser `atob`/`btoa` DOMString policy, data URLs, cryptographic
integrity, or canonical-signature validation. Those are separate protocol or security
surfaces.
