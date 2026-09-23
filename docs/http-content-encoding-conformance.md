# HTTP Content-Encoding interoperability

This domain composes a controlled loopback HTTP transport with each runtime's native
HTTP client response-body policy. The case never supplies a URL, host, or port. Each
worker owns a one-shot server bound to `127.0.0.1`, constructs its own URL, serves the
case-provided wire body, and then observes that response through the native client.

## Case protocol

Each stdin case is binary and exact:

- byte 0: response mode (`0` = no Content-Encoding, `1` = `gzip`);
- bytes 1..4: unsigned big-endian wire-body length;
- remaining bytes: exact response wire body.

Unknown modes, truncated framing, trailing bytes, and inconsistent lengths fail closed as
`protocol_error`. The case cannot influence request routing or server addressing.

## Runtime implementations

- Python uses `urllib.request.urlopen`.
- Node uses built-in `fetch`, whose response decoding policy is implemented through the
  Node/Undici/zlib stack.

The server always returns status 200, `Content-Type: application/octet-stream`, an exact
wire `Content-Length`, optional `Content-Encoding: gzip`, and
`Connection: close`.

Successful observations record the body bytes seen by the client plus the native
Content-Encoding and Content-Length response headers.

## Bounded execution

Two independent target budgets are immutable replay configuration:

- `max_wire_body_bytes`: caps the response body supplied by the case before the
  loopback server starts;
- `max_observed_body_bytes`: caps the body bytes exposed by the native client before
  result serialization.

Python reads at most one byte past the observed-body ceiling. Node consumes the decoded
Fetch body as a stream and cancels it as soon as accumulated output exceeds the ceiling.
This keeps automatic gzip expansion from making generic stdout capture the first decoded
body bound.

The configured ceilings are capped at 1 MiB. Python implementation/version and
Node/Undici/zlib runtime identity participate in replay context.

## Executable evidence

Identity responses establish the shared HTTP path: empty, text, and arbitrary binary
bodies must match exactly.

For `Content-Encoding: gzip`, the native policy intentionally remains visible. Python
urllib exposes the gzip wire bytes while Node Fetch automatically exposes the decoded
payload, even though both retain the gzip Content-Encoding header and the wire
Content-Length. Malformed gzip therefore also diverges: Python can observe the raw bytes
while Node reports a body decode failure.

A separate expansion regression serves a small gzip wire body whose decoded response
exceeds the observed-body ceiling. Node fails closed at the decoded-body bound while
Python's raw-wire observation remains within it. Deterministic discovery publishes and
replays a valid gzip auto-decoding mismatch through the existing repro substrate.

## Scope boundary

This checkpoint does not expose arbitrary network destinations and makes no SSRF claim
beyond this adapter's fixed loopback construction. It does not claim HTTP/2 or HTTP/3,
TLS, redirects, proxies, cookies, caching, transfer-encoding interoperability, brotli or
deflate semantics, streaming backpressure equivalence, browser Fetch behavior, or
performance results.
