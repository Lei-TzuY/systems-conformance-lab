# Data URL fetch interoperability

This adapter pair exercises a complete `data:` URL fetch/decode path through real
Python and Node child processes.

## Semantic contract

Input is raw stdin bytes. The domain accepts ASCII `data:` URLs only and emits:

- the native response `Content-Type` value;
- the exact decoded body bytes as lowercase hexadecimal.

A strict case-insensitive `data:` scheme gate runs before either native URL API. Inputs
such as `http:`, `file:`, and `javascript:` therefore cannot escape the conformance
case into network, filesystem, or script access.

Each target has an independent data-URL byte ceiling. The worker stops consuming stdin
after one byte beyond the configured limit and reports `data_url_too_large`. Since data
URL percent decoding and Base64 decoding do not expand beyond the source URL payload,
this also bounds decoded body materialization. The ceiling is capped at 1 MiB and is part
of replay identity.

## Runtime implementations

- Python uses `urllib.request.urlopen` after the scheme gate.
- Node uses the built-in `fetch` implementation after the same gate.

Python implementation/version and Node/Undici versions are captured at target
construction, verified before case processing, and therefore participate in the existing
replay-context hash.

## Executable evidence

The shared surface covers:

- default `text/plain;charset=US-ASCII` metadata;
- explicit media types and parameters;
- percent-decoded text and arbitrary binary bytes;
- valid Base64 payloads;
- percent-encoded Base64 padding;
- case-insensitive `data:` scheme spelling;
- empty payloads;
- malformed data URLs;
- exact and over-limit URL byte boundaries.

Native policy remains visible rather than being normalized away:

- Node accepts missing Base64 padding that Python rejects;
- Python accepts selected extra-padding and non-alphabet Base64 spellings that Node
  rejects;
- Node recognizes `;BASE64` as the Base64 marker case-insensitively, while Python
  treats uppercase `BASE64` as media-type metadata and leaves the payload undecoded.

The uppercase-marker case is a cross-layer MIME/Base64 dispatch witness. A deterministic
discovery campaign publishes that product mismatch through the generic repro path, and
replay must reproduce the same stable failure signature.

## Scope boundary

This checkpoint covers in-process `data:` fetch/decode semantics only. It does not claim
HTTP fetching, file URL access, browser origin/CSP behavior, navigation, Blob URLs,
streaming response consumption, multipart parsing, MIME sniffing, charset transcoding,
or cryptographic integrity.
