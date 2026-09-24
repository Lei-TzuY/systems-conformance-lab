from __future__ import annotations

from collections.abc import Iterator

from .multipart_form_data_adapter import MULTIPART_FORM_DATA_BOUNDARY

_BOUNDARY = MULTIPART_FORM_DATA_BOUNDARY.encode("ascii")
_DELIMITER = b"--" + _BOUNDARY
_FILENAME_STAR_PREFIXES = (b"; filename*=UTF-8''", b"; filename*=UTF-8'en'")
_HEX = frozenset(b"0123456789ABCDEFabcdef")
_ATTR_CHAR = frozenset(b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789!#$&+-.^_`|~")


def _parse_parts(raw: bytes) -> tuple[tuple[tuple[bytes, ...], bytes], ...]:
    """Parse the canonical multipart corpus framing or fail closed."""
    if not raw.startswith(_DELIMITER + b"\r\n"):
        raise ValueError("non-canonical opening boundary")
    if not raw.endswith(_DELIMITER + b"--\r\n"):
        raise ValueError("missing canonical closing boundary")
    offset = len(_DELIMITER) + 2
    parts: list[tuple[tuple[bytes, ...], bytes]] = []
    marker = b"\r\n" + _DELIMITER
    while True:
        header_end = raw.find(b"\r\n\r\n", offset)
        if header_end < 0:
            raise ValueError("truncated multipart headers")
        headers = tuple(raw[offset:header_end].split(b"\r\n"))
        if not headers or any(not header for header in headers):
            raise ValueError("empty multipart header")
        for header in headers:
            try:
                header.decode("ascii")
            except UnicodeDecodeError as exc:
                raise ValueError("non-ASCII multipart header") from exc
            if b":" not in header or header.startswith((b" ", b"\t")):
                raise ValueError("non-canonical multipart header")
        body_start = header_end + 4
        boundary_at = raw.find(marker, body_start)
        if boundary_at < 0:
            raise ValueError("missing multipart boundary")
        parts.append((headers, raw[body_start:boundary_at]))
        boundary_start = boundary_at + 2
        after = boundary_start + len(_DELIMITER)
        if raw[after : after + 4] == b"--\r\n":
            if after + 4 != len(raw):
                raise ValueError("multipart epilogue is not reducible")
            return tuple(parts)
        if raw[after : after + 2] != b"\r\n":
            raise ValueError("non-canonical multipart boundary")
        offset = after + 2


def _encode_parts(parts: tuple[tuple[tuple[bytes, ...], bytes], ...]) -> bytes:
    framed = bytearray()
    for headers, body in parts:
        framed.extend(_DELIMITER)
        framed.extend(b"\r\n")
        framed.extend(b"\r\n".join(headers))
        framed.extend(b"\r\n\r\n")
        framed.extend(body)
        framed.extend(b"\r\n")
    framed.extend(_DELIMITER)
    framed.extend(b"--\r\n")
    return bytes(framed)


def _filename_star_header_reductions(header: bytes) -> tuple[bytes, ...]:
    """Shrink exact target-owned RFC 5987 filename* payload forms.

    Fully percent-encoded payloads and mixed one-percent-plus-attr-char payloads accept
    either the empty language field or the fixed ``en`` tag emitted by our mutators.
    Other syntax is untouched so reduction cannot normalize policy-bearing or ambiguous
    Content-Disposition input.
    """
    if not header.startswith(b"Content-Disposition:"):
        return ()
    matches = [(header.find(prefix), prefix) for prefix in _FILENAME_STAR_PREFIXES if header.find(prefix) >= 0]
    if len(matches) != 1:
        return ()
    marker_at, marker = matches[0]
    if header.find(marker, marker_at + 1) >= 0:
        return ()
    encoded = header[marker_at + len(marker) :]
    prefix = header[: marker_at + len(marker)]

    if (
        len(encoded) >= 4
        and encoded[0] == ord("%")
        and all(byte in _HEX for byte in encoded[1:3])
        and all(byte in _ATTR_CHAR for byte in encoded[3:])
    ):
        suffix = encoded[3:]
        sizes = (max(1, len(suffix) // 2), 1)
        reductions: list[bytes] = []
        for size in sizes:
            candidate = prefix + encoded[:3] + suffix[:size]
            if candidate != header and candidate not in reductions:
                reductions.append(candidate)
        return tuple(reductions)

    if len(encoded) < 6 or len(encoded) % 3:
        return ()
    if any(encoded[index] != ord("%") for index in range(0, len(encoded), 3)):
        return ()
    if any(byte not in _HEX for index in range(0, len(encoded), 3) for byte in encoded[index + 1 : index + 3]):
        return ()
    octets = len(encoded) // 3
    sizes = (max(1, octets // 2), 1)
    reductions = []
    for size in sizes:
        candidate = prefix + encoded[: size * 3]
        if candidate != header and candidate not in reductions:
            reductions.append(candidate)
    return tuple(reductions)


def multipart_form_data_reduction_candidates(raw: bytes) -> Iterator[bytes]:
    """Yield deterministic, unique, strictly smaller canonical multipart cases."""
    parts = _parse_parts(raw)
    seen: set[bytes] = set()

    def emit(candidate_parts: tuple[tuple[tuple[bytes, ...], bytes], ...]) -> Iterator[bytes]:
        candidate = _encode_parts(candidate_parts)
        if len(candidate) < len(raw) and candidate not in seen:
            seen.add(candidate)
            yield candidate

    if len(parts) > 1:
        for index in range(len(parts)):
            yield from emit(parts[:index] + parts[index + 1 :])
    for index, (headers, body) in enumerate(parts):
        if body:
            reductions = (b"",)
            if len(body) > 1:
                reductions += (body[: len(body) // 2], body[-1:])
            for reduced in reductions:
                candidate_parts = list(parts)
                candidate_parts[index] = (headers, reduced)
                yield from emit(tuple(candidate_parts))
        for header_index, header in enumerate(headers):
            for reduced_header in _filename_star_header_reductions(header):
                reduced_headers = list(headers)
                reduced_headers[header_index] = reduced_header
                candidate_parts = list(parts)
                candidate_parts[index] = (tuple(reduced_headers), body)
                yield from emit(tuple(candidate_parts))
