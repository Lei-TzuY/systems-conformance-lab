from __future__ import annotations

from collections.abc import Iterator

from .multipart_form_data_reducer import _encode_parts, _parse_parts

_MAX_MUTATION_INPUT_BYTES = 64 * 1024
_MAX_PARTS = 64
_UTF8_CONTENT_TYPE = b"Content-Type: text/plain; charset=utf-8"
_LATIN1_CONTENT_TYPE = b"Content-Type: text/plain; charset=iso-8859-1"


def multipart_form_data_charset_mutations(raw: bytes) -> Iterator[bytes]:
    """Yield bounded deterministic charset-policy mutations for canonical form-data.

    A mutation preserves the Unicode text represented by one UTF-8 text part while
    switching its explicit charset and body bytes to ISO-8859-1. Only text that is
    representable in Latin-1 is eligible. Malformed/non-canonical multipart input,
    oversized input, or excessive part counts fail closed rather than being repaired.
    """
    if len(raw) > _MAX_MUTATION_INPUT_BYTES:
        raise ValueError("multipart mutation input exceeds byte budget")

    parts = _parse_parts(raw)
    if len(parts) > _MAX_PARTS:
        raise ValueError("multipart mutation input exceeds part budget")

    for index, (headers, body) in enumerate(parts):
        if _UTF8_CONTENT_TYPE not in headers:
            continue
        try:
            text = body.decode("utf-8")
            latin1 = text.encode("iso-8859-1")
        except UnicodeError:
            continue
        if latin1 == body:
            continue

        mutated_headers = tuple(
            _LATIN1_CONTENT_TYPE if header == _UTF8_CONTENT_TYPE else header
            for header in headers
        )
        candidate_parts = list(parts)
        candidate_parts[index] = (mutated_headers, latin1)
        candidate = _encode_parts(tuple(candidate_parts))
        if candidate != raw:
            yield candidate
