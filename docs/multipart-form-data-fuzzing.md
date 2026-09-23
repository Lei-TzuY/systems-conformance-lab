# Multipart form-data charset mutation

The multipart/form-data target has a bounded domain-aware mutation step that can turn a matching UTF-8 text part into an equivalent ISO-8859-1 representation. The Unicode text is preserved while both the explicit charset parameter and body bytes change, so a campaign can discover parser policy differences rather than merely enumerate a prewritten failing fixture.

Mutation accepts only the same canonical multipart framing used by the structural reducer. Input is capped at 64 KiB and 64 parts before candidates are constructed. Only exact `Content-Type: text/plain; charset=utf-8` parts whose body is valid UTF-8 and fully representable in Latin-1 are eligible. Malformed framing and oversized structures fail closed; invalid or non-Latin-1 text is not repaired into a candidate.

The integration regression starts from a UTF-8 `café` case that matches across the real Python stdlib and Node `Response.formData()` child-process targets. The deterministic charset mutation preserves the text while changing its representation to ISO-8859-1, and the normal failure-discovery campaign then observes the native runtime policy difference as a product mismatch. Generic fuzz scheduling and failure classification remain unchanged.
