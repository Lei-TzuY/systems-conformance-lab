from __future__ import annotations

from collections.abc import Iterator

from .multipart_form_data_adapter import MULTIPART_FORM_DATA_BOUNDARY

_BOUNDARY = MULTIPART_FORM_DATA_BOUNDARY.encode("ascii")
_DELIMITER = b"--" + _BOUNDARY


def _parse_parts(raw: bytes) -> tuple[tuple[tuple[bytes, ...], bytes], ...]:
    """Parse the canonical multipart corpus framing or fail closed.

    Reduction accepts only CRLF-delimited parts with a final closing boundary,
    non-empty ASCII header lines, and no preamble/epilogue. This deliberately
    excludes LF-only, malformed, or ambiguous multipart input rather than
    normalizing it into a different test case.
    """
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
        header_block = raw[offset:header_end]
        headers = tuple(header_block.split(b"\r\n"))
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
        body = raw[body_start:boundary_at]
        parts.append((headers, body))

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


def multipart_form_data_reduction_candidates(raw: bytes) -> Iterator[bytes]:
    """Yield deterministic, unique, strictly smaller canonical multipart cases.

    Candidates remove complete parts or shrink part bodies while preserving
    target-owned boundary/header semantics. Header mutation is intentionally
    excluded: Content-Disposition and Content-Type policy differences remain
    intact, and malformed input is rejected instead of repaired.
    """
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
        if not body:
            continue
        reductions = (b"",)
        if len(body) > 1:
            reductions += (body[: len(body) // 2], body[-1:])
        for reduced in reductions:
            candidate_parts = list(parts)
            candidate_parts[index] = (headers, reduced)
            yield from emit(tuple(candidate_parts))
