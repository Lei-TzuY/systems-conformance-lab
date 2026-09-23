# Gzip decompression interoperability

This adapter pair exercises bounded gzip decompression through real Python and Node
child processes.

## Semantic contract

Input is raw gzip transport bytes. Successful decompression emits the exact decoded bytes
as lowercase hexadecimal. Decode failures are projected to one canonical
`gzip_decode_error` result, while expansion beyond the configured decoded-output ceiling
is projected to `decompressed_output_too_large`.

The decoded-output ceiling is enforced inside each target rather than relying on generic
stdout truncation:

- Python reads through `gzip.GzipFile` at most one byte beyond the configured limit.
- Node calls `zlib.gunzipSync` with `maxOutputLength = limit + 1`.

The configuration is bounded to at most 16 MiB and participates in replay identity.

## Runtime identity

Python captures implementation/version and `zlib.ZLIB_RUNTIME_VERSION`. Node captures
Node and `process.versions.zlib`. Workers verify those values before consuming the case,
so a runtime or zlib upgrade changes replay context instead of silently reusing old
evidence.

## Executable evidence

The shared surface covers:

- empty and binary decoded payloads;
- concatenated gzip members with ordered output;
- trailing zero padding;
- malformed headers;
- truncated streams;
- CRC corruption;
- exact decoded-output limits;
- fail-closed over-limit expansion.

Native policy is intentionally preserved. Two stable differences are executable:

- Python treats an empty transport as an empty gzip stream while Node rejects it.
- After a valid member, Node accepts a zero byte followed by non-zero trailing data in
  cases where Python's gzip reader rejects the trailing bytes.

A deterministic discovery campaign starts from a valid gzip member, adds the
`00 01` trailing suffix, publishes that product mismatch through the generic repro
path, and replay must reproduce the same stable failure signature.

## Scope boundary

This slice is decompression-only. It does not claim deterministic gzip encoding bytes,
DEFLATE-level equivalence, ZIP compatibility, HTTP Content-Encoding behavior,
dictionary compression, streaming backpressure, or benchmark/performance results.
