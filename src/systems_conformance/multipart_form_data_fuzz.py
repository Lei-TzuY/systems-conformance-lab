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
_ATTR_CHAR = frozenset(b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789!#$&+-.^_`|~")


def _bounded_parts(raw: bytes) -> tuple[tuple[tuple[bytes, ...], bytes], ...]:
    if len(raw) > _MAX_MUTATION_INPUT_BYTES:
        raise ValueError("multipart mutation input exceeds byte budget")
    parts = _parse_parts(raw)
    if len(parts) > _MAX_PARTS:
        raise ValueError("multipart mutation input exceeds part budget")
    return parts


def multipart_form_data_charset_mutations(raw: bytes) -> Iterator[bytes]:
    """Yield bounded deterministic charset-policy mutations for canonical form-data."""
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
    mixed_percent_attr: bool = False,
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
            if mixed_percent_attr and (
                len(filename) < 2 or any(byte not in _ATTR_CHAR for byte in filename[1:])
            ):
                continue

            prefix = header[: marker_index + 1]
            if mixed_percent_attr:
                encoded = f"%{filename[0]:02X}".encode("ascii") + filename[1:]
            elif percent_encode_all:
                hex_format = "02x" if lowercase_percent_hex else "02X"
                encoded = b"".join(
                    f"%{byte:{hex_format}}".encode("ascii") for byte in filename
                )
            else:
                encoded = quote_from_bytes(filename, safe="!#$&+-.^_`|~").encode("ascii")
            mutated_header = prefix + b"; filename*=UTF-8'" + language_tag + b"'" + encoded
            mutated_headers = list(headers)
            mutated_headers[header_index] = mutated_header
            candidate_parts = list(parts)
            candidate_parts[part_index] = (tuple(mutated_headers), body)
            candidate = _encode_parts(tuple(candidate_parts))
            if candidate != raw:
                yield candidate


def multipart_form_data_filename_star_mutations(raw: bytes) -> Iterator[bytes]:
    """Yield semantic-preserving RFC 5987 filename* policy mutations."""
    yield from _filename_star_mutations(raw, percent_encode_all=False)


def multipart_form_data_filename_star_percent_mutations(raw: bytes) -> Iterator[bytes]:
    """Yield RFC 5987 filename* mutations with every filename byte percent encoded."""
    yield from _filename_star_mutations(raw, percent_encode_all=True)


def multipart_form_data_filename_star_lowercase_percent_mutations(raw: bytes) -> Iterator[bytes]:
    """Yield RFC 5987 filename* mutations using lowercase percent-escape hex digits."""
    yield from _filename_star_mutations(raw, percent_encode_all=True, lowercase_percent_hex=True)


def multipart_form_data_filename_star_mixed_percent_mutations(raw: bytes) -> Iterator[bytes]:
    """Yield filename* mutations mixing one percent octet with attr-char bytes."""
    yield from _filename_star_mutations(raw, percent_encode_all=False, mixed_percent_attr=True)


def multipart_form_data_filename_star_language_mixed_percent_mutations(raw: bytes) -> Iterator[bytes]:
    """Yield fixed-language filename* mutations mixing percent and attr-char bytes.

    The target-owned representation combines the deterministic ``en`` language field
    with exactly one leading percent-encoded octet and a non-empty RFC 5987 attr-char
    suffix. This crosses both decoder policy boundaries while preserving the original
    ASCII filename semantics and the existing bounded fail-closed multipart parser.
    """
    yield from _filename_star_mutations(
        raw, percent_encode_all=False, language_tag=b"en", mixed_percent_attr=True
    )


def multipart_form_data_filename_star_language_mutations(raw: bytes) -> Iterator[bytes]:
    """Yield RFC 5987 filename* mutations carrying a deterministic language tag."""
    yield from _filename_star_mutations(raw, percent_encode_all=True, language_tag=b"en")
