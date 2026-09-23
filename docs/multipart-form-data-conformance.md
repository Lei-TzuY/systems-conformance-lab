# Multipart/form-data parser interoperability

This checkpoint promotes the conformance lab into a MIME/form-data parsing domain using
separate real Python and Node child-process targets.

## Semantic contract

Input is the raw multipart body only. Both targets receive the same immutable boundary:

`systems-conformance-boundary`

The outer Content-Type is constructed by the target rather than supplied by the case.
This keeps the fuzz/repro input entirely inside the message body and prevents the test
surface from turning into an HTTP transport or external-resource problem.

Successful output preserves form entry order and duplicate names. To keep result
serialization itself out of the comparison surface:

- field names are emitted as UTF-8 hexadecimal;
- text values are the native parser's decoded string re-encoded to UTF-8 hexadecimal;
- file names are emitted as UTF-8 hexadecimal;
- file bodies are emitted as raw-byte hexadecimal;
- file Content-Type is retained as a string.

## Runtime implementations

- Python uses `email.parser.BytesParser` with the stdlib default policy and an injected
  multipart/form-data Content-Type header.
- Node uses the built-in `Response(...).formData()` implementation.

Python implementation/version and Node/Undici versions are captured when targets are
constructed, verified before stdin processing, and therefore participate in replay
identity.

## Bounded execution

Each target has an independent raw-body ceiling, defaulting to 64 KiB and capped at
256 KiB. Inputs over the limit fail closed as `input_too_large` before native multipart
parsing. Multipart parsing does not decompress the body or follow external references;
the bounded input therefore also bounds file payload materialization and the number of
parts that can be represented.

## Executable shared evidence

The integration suite covers:

- ordinary text fields;
- duplicate field names with preserved order;
- empty text fields;
- UTF-8 text with an explicit charset;
- binary file payloads including NUL and non-UTF-8 bytes;
- file name and Content-Type preservation;
- malformed non-multipart input;
- exact and over-limit body budgets.

## Native policy differences

The targets deliberately keep real parser policy visible instead of normalizing it away:

- Python's email parser honors `charset=iso-8859-1` for text payloads, while Node
  FormData decodes the same byte through its UTF-8 text path and produces a replacement
  character;
- Python accepts LF-only multipart framing that Node rejects;
- Python resolves RFC-style `filename*=` parameters in Content-Disposition while Node
  rejects that body as FormData.

The charset case is used as deterministic discovery evidence because both parsers accept
the message while producing different text semantics. Discovery publishes the mismatch
through the existing repro path, and replay must reproduce the same stable failure
signature.

## Scope boundary

This phase does not claim browser form submission, HTTP transport, streaming multipart
parsing/backpressure, MIME sniffing, nested multipart support, transfer-encoding
interoperability, arbitrary boundary generation, disk-backed upload spooling, or
performance results.
