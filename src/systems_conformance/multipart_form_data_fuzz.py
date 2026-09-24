from __future__ import annotations

from collections.abc import Iterator
from urllib.parse import quote_from_bytes

from .multipart_form_data_reducer import _encode_parts, _parse_parts

_MAX_MUTATION_INPUT_BYTES = 64 * 1024
_MAX_PARTS = 64
_UTF8_CONTENT_TYPE = b"Content-Type: text/plain; charset=utf-8"
_LATIN1_CONTENT_TYPE = b"Content-Type: text/plain; charset=iso-8859-1"
_CONTENT_DISPOSITION_PREFIX = b'Content-Disposition: form-data; name="'
_FILENAME_MARKER = b'"; filename="'


def _bounded_parts(raw: bytes) -> tuple[tuple[tuple[bytes, ...], bytes], ...]:
    if len(raw) > _MAX_MUTATION_INPUT_BYTES:
        raise ValueError("multipart mutation input exceeds byte budget")
    parts = _parse_parts(raw)
    if len(parts) > _MAX_PARTS:
        raise ValueError("multipart mutation input exceeds part budget")
    return parts


def multipart_form_data_charset_mutations(raw: bytes) -> Iterator[bytes]:
    """Yield bounded deterministic charset-policy mutations for canonical form-data.

    A mutation preserves the Unicode text represented by one UTF-8 text part while
    switching its explicit charset and body bytes to ISO-8859-1. Only text that is
    representable in Latin-1 is eligible. Malformed/non-canonical multipart input,
    oversized input, or excessive part counts fail closed rather than being repaired.
    """
    parts = _bounded_parts(raw)

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


def _filename_star_mutations(
    raw: bytes,
    *,
    percent_encode_all: bool,
    language_tag: bytes = b"",
    lowercase_percent_hex: bool = False,
) -> Iterator[bytes]:
    parts = _bounded_parts(raw)

    for part_index, (headers, body) in enumerate(parts):
        for header_index, header in enumerate(headers):
            if not header.startswith(_CONTENT_DISPOSITION_PREFIX):
                continue
            marker_index = header.find(_FILENAME_MARKER)
            if marker_index < 0 or not header.endswith(b'"'):
                continue
            filename_start = marker_index + len(_FILENAME_MARKER)
            filename = header[filename_start:-1]
            if not filename or any(byte < 0x20 or byte > 0x7E for byte in filename):
                continue
            if any(byte in b'"\\%;' for byte in filename):
                continue

            prefix = header[: marker_index + 1]
            if percent_encode_all:
                hex_format = "02x" if lowercase_percent_hex else "02X"
                encoded = b"".join(
                    f"%{byte:{hex_format}}".encode("ascii") for byte in filename
                )
            else:
                encoded = quote_from_bytes(filename, safe="!#$&+-.^_`|~").encode("ascii")
            mutated_header = (
                prefix + b"; filename*=UTF-8'" + language_tag + b"'" + encoded
            )
            mutated_headers = list(headers)
            mutated_headers[header_index] = mutated_header
            candidate_parts = list(parts)
            candidate_parts[part_index] = (tuple(mutated_headers), body)
            candidate = _encode_parts(tuple(candidate_parts))
            if candidate != raw:
                yield candidate


def multipart_form_data_filename_star_mutations(raw: bytes) -> Iterator[bytes]:
    """Yield semantic-preserving RFC 5987 filename* policy mutations.

    Only the canonical ASCII ``filename="..."`` form emitted by the shared multipart
    subset is eligible. The filename bytes must be printable ASCII without quoting or
    percent characters; this keeps the source semantics unambiguous. The mutation
    replaces exactly one filename parameter with an equivalent UTF-8 ``filename*``
    parameter. Malformed/non-canonical multipart input and budget violations fail
    closed through the same bounded parser used by the charset mutation.
    """
    yield from _filename_star_mutations(raw, percent_encode_all=False)


def multipart_form_data_filename_star_percent_mutations(raw: bytes) -> Iterator[bytes]:
    """Yield RFC 5987 filename* mutations with every filename byte percent encoded.

    This exercises extended-parameter percent decoding independently of attr-char
    handling while preserving the same ASCII filename semantics. Eligibility, input
    budgets, and fail-closed parsing are identical to the ordinary filename* mutation.
    """
    yield from _filename_star_mutations(raw, percent_encode_all=True)


def multipart_form_data_filename_star_lowercase_percent_mutations(
    raw: bytes,
) -> Iterator[bytes]:
    """Yield RFC 5987 filename* mutations using lowercase percent-escape hex digits.

    Percent escapes are case-insensitive, so this preserves the same filename semantics
    while exercising a distinct decoder representation. Eligibility, input budgets, and
    fail-closed parsing remain identical to the other target-owned filename* mutations.
    """
    yield from _filename_star_mutations(
        raw, percent_encode_all=True, lowercase_percent_hex=True
    )


def multipart_form_data_filename_star_language_mutations(raw: bytes) -> Iterator[bytes]:
    """Yield RFC 5987 filename* mutations carrying a deterministic language tag.

    The fixed ``en`` tag changes only extended-parameter metadata, not the represented
    filename. Source eligibility and bounded fail-closed parsing are identical to the
    ordinary filename* mutation so untrusted multipart input is never repaired.
    """
    yield from _filename_star_mutations(
        raw, percent_encode_all=True, language_tag=b"en"
    )
