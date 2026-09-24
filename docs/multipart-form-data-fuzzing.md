# Multipart form-data policy mutation

The multipart/form-data target has bounded domain-aware mutation steps that start from matching canonical inputs and preserve their intended application semantics while changing parser-policy representation. This lets a campaign discover native runtime policy differences rather than merely enumerate prewritten failing fixtures.

## Charset representation

A charset mutation can turn a matching UTF-8 text part into an equivalent ISO-8859-1 representation. The Unicode text is preserved while both the explicit charset parameter and body bytes change. Only exact `Content-Type: text/plain; charset=utf-8` parts whose body is valid UTF-8 and fully representable in Latin-1 are eligible.

The integration regression starts from a UTF-8 `café` case that matches across the real Python stdlib and Node `Response.formData()` child-process targets. The deterministic charset mutation preserves the text while changing its representation to ISO-8859-1, and the normal failure-discovery campaign then observes the native runtime policy difference as a product mismatch.

## Content-Disposition filename representation

A filename mutation starts from the shared subset's canonical ASCII `filename="..."` parameter and replaces exactly one eligible filename with the semantically equivalent RFC 5987 `filename*=UTF-8''...` representation. Eligibility is intentionally narrow: filenames must be non-empty printable ASCII and may not contain quote, backslash, percent, or semicolon characters. Existing `filename*` parameters and ambiguous forms are not rewritten.

The real-target integration starts from a `filename="plain.txt"` file part that matches across Python and Node. Mutation produces `filename*=UTF-8''plain.txt`; Python's stdlib parser accepts the extended parameter while Node `Response.formData()` rejects that form, so ordinary failure discovery records a product mismatch generated from a matching seed.

A second deterministic mutation exercises RFC 5987 percent decoding separately from attr-char handling by percent-encoding every byte of the same eligible ASCII filename. For example, `plain.txt` becomes `%70%6C%61%69%6E%2E%74%78%74`. The represented filename is unchanged, so the real-target campaign can probe extended-parameter decoding without changing application semantics or introducing a prewritten failing witness.

A third deterministic mutation exercises the RFC 5987 language-tag field by emitting the fixed `en` tag together with the fully percent-encoded filename, for example `filename*=UTF-8'en'%70%6C%61%69%6E%2E%74%78%74`. The language metadata does not alter the represented filename. Keeping the tag fixed makes the campaign deterministic while forcing real targets through the non-empty language-field parsing path.

## Bounds and trust model

All mutation paths accept only the canonical multipart framing used by the structural reducer. Input is capped at 64 KiB and 64 parts before candidates are constructed. Malformed framing and oversized structures fail closed rather than being repaired. Generic fuzz scheduling and failure classification remain unchanged.
