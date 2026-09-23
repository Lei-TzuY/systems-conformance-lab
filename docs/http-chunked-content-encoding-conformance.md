# HTTP chunked plus Content-Encoding interoperability

This checkpoint composes two previously independent loopback HTTP domains into one real
native-client pipeline: HTTP/1.1 chunked transfer framing and response Content-Encoding.

The case never supplies a URL, host, port, status, or response header. Each worker binds a
one-shot server to `127.0.0.1`, constructs its own URL, and sends the case-provided raw
chunked transfer body beneath fixed response headers.

## Case protocol

The stdin case is binary:

- byte 0: content mode (`0` = identity, `1` = `Content-Encoding: gzip`);
- remaining bytes: exact bytes after the HTTP response header terminator.

Unknown or missing modes fail closed as `protocol_error`. The raw transfer body cannot
inject or alter response headers because it is appended only after the fixed header
terminator.

## Runtime implementations

- Python uses a raw socket one-shot server plus `urllib.request.urlopen`.
- Node uses a raw `node:net` one-shot server plus built-in `fetch`.

Both servers always emit status 200, `Content-Type: application/octet-stream`,
`Transfer-Encoding: chunked`, and `Connection: close`. Gzip mode additionally emits
`Content-Encoding: gzip`.

Successful results record the body exposed by the native client together with
Transfer-Encoding, Content-Encoding, and Content-Length observations.

## Bounded execution

Two independent target budgets are immutable replay configuration:

- `max_transfer_body_bytes` bounds the exact raw chunk-framing bytes before the loopback
  server starts;
- `max_observed_body_bytes` bounds the body bytes exposed by the native client after its
  transfer/content processing.

Python reads at most one byte beyond the observed-body ceiling. Node reads the Fetch body
incrementally and cancels when accumulated output exceeds the ceiling. This keeps gzip
expansion bounded after dechunking rather than relying on generic stdout capture.

Configured budgets are capped at 1 MiB. Python implementation/version and
Node/Undici/zlib versions participate in replay identity.

## Executable evidence

Identity mode proves that both clients reconstruct ordinary chunked responses consistently,
including empty, text, and arbitrary binary bodies.

Gzip mode then proves the cross-layer policy difference. Both clients first reconstruct the
chunked entity body. Python urllib exposes the resulting gzip bytes without content
decoding, while Node Fetch/Undici automatically exposes the decompressed payload. Both
retain `Transfer-Encoding: chunked` and `Content-Encoding: gzip`, while Content-Length
remains absent.

A valid chunk framing around malformed gzip bytes isolates the content-decoding stage:
Python can expose the reconstructed malformed gzip bytes, while Node reports
`body_decode_error`. A gzip expansion regression demonstrates that Node's decoded body
remains bounded after transfer framing is removed.

Deterministic discovery publishes and replays a valid chunked+gzip auto-decoding mismatch
through the existing repro substrate.

## Scope boundary

This checkpoint covers controlled HTTP/1.1 response-side interaction only. It does not
claim arbitrary network destinations, request-body chunking, HTTP/2 or HTTP/3, TLS,
redirects, proxies, cookies, caching, trailer API parity, brotli/deflate, request
smuggling/security analysis, browser Fetch behavior, streaming-backpressure equivalence,
or performance results.
