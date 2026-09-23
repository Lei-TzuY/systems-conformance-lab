# HTTP chunked-transfer interoperability

This domain promotes the loopback HTTP surface from content decoding into HTTP/1.1
transfer framing. Each runtime receives the same raw chunked transfer body from a
target-owned one-shot server and observes it through its native HTTP client.

## Isolation contract

The case contains only the bytes that follow the HTTP response header terminator.
The target always constructs:

- a server bound to `127.0.0.1`;
- a target-owned ephemeral port and URL;
- status `200 OK`;
- `Content-Type: application/octet-stream`;
- `Transfer-Encoding: chunked`;
- `Connection: close`.

The case cannot choose a host, port, method, status, header, or external destination.

## Runtime implementations

- Python uses a raw socket one-shot server plus `urllib.request.urlopen`.
- Node uses a raw `node:net` one-shot server plus built-in `fetch`.

The servers write the case bytes without re-framing them, so malformed chunk syntax is
observed by the native clients rather than corrected by an HTTP server library.

Successful output records the reconstructed body, native Transfer-Encoding header, and
Content-Length header (normally absent under chunked transfer).

## Bounded execution

Two replay-bound ceilings are enforced independently:

- `max_transfer_body_bytes` caps the exact raw chunk framing bytes supplied by the case
  before a loopback server starts;
- `max_observed_body_bytes` caps the reconstructed body exposed by the native client.

Python reads at most one byte beyond the observed-body ceiling. Node reads the Fetch body
incrementally and cancels when accumulated output exceeds the ceiling. Both configured
budgets are capped at 1 MiB.

Python implementation/version and Node/Undici versions are captured at target
construction, verified before case processing, and therefore participate in replay
identity.

## Executable evidence

The shared surface covers:

- empty chunked bodies;
- single and multiple chunks;
- arbitrary binary chunk payloads;
- hexadecimal chunk-size case;
- chunk extensions;
- trailers;
- malformed hexadecimal sizes;
- LF-only framing rejection;
- exact and over-limit transfer-body budgets;
- exact and over-limit reconstructed-body budgets.

Native premature-close policy remains visible. For a chunk declaring five bytes but a
connection that closes after three payload bytes, Python raises an incomplete-read
failure while Node Fetch/Undici exposes the three received bytes as a successful body.
A deterministic discovery campaign publishes that product mismatch through the generic
repro path, and replay must reproduce the same stable failure signature.

## Scope boundary

This checkpoint covers HTTP/1.1 response-side chunked transfer framing only. It does not
claim request-body chunking, HTTP/2 or HTTP/3 framing, TLS, redirects, proxies, cookies,
caching, Content-Encoding interaction, trailer API parity, streaming backpressure
equivalence, browser Fetch behavior, request smuggling/security analysis, or performance
results.
