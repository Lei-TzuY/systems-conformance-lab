from __future__ import annotations

from collections.abc import Iterator


def _parse_case(raw: bytes) -> tuple[int, tuple[bytes, ...]]:
    """Parse the bounded chunked-content case protocol or fail closed.

    Reduction intentionally accepts only the canonical chunk framing emitted by the
    conformance corpus: hexadecimal sizes, CRLF delimiters, no extensions/trailers,
    and one final zero chunk. This avoids normalizing malformed or ambiguous HTTP.
    """
    if not raw or raw[0] not in (0, 1):
        raise ValueError("invalid content-encoding mode")

    body = raw[1:]
    offset = 0
    chunks: list[bytes] = []
    while True:
        line_end = body.find(b"\r\n", offset)
        if line_end < 0:
            raise ValueError("truncated chunk-size line")
        size_token = body[offset:line_end]
        if not size_token or b";" in size_token:
            raise ValueError("non-canonical chunk-size line")
        try:
            size = int(size_token, 16)
        except ValueError as exc:
            raise ValueError("invalid chunk size") from exc
        if size_token.upper() != f"{size:X}".encode("ascii"):
            raise ValueError("non-canonical chunk size")
        offset = line_end + 2
        if size == 0:
            if body[offset:] != b"\r\n":
                raise ValueError("trailers or trailing bytes are not reducible")
            return raw[0], tuple(chunks)
        end = offset + size
        if end + 2 > len(body) or body[end : end + 2] != b"\r\n":
            raise ValueError("chunk payload exceeds framing")
        chunks.append(body[offset:end])
        offset = end + 2


def _encode_case(mode: int, chunks: tuple[bytes, ...]) -> bytes:
    framed = bytearray([mode])
    for chunk in chunks:
        if not chunk:
            continue
        framed.extend(f"{len(chunk):X}\r\n".encode("ascii"))
        framed.extend(chunk)
        framed.extend(b"\r\n")
    framed.extend(b"0\r\n\r\n")
    return bytes(framed)


def http_chunked_content_encoding_reduction_candidates(raw: bytes) -> Iterator[bytes]:
    """Yield deterministic, unique, strictly smaller canonical chunked cases.

    Candidates preserve the target-owned content-encoding mode while shrinking only
    case-controlled transfer framing. They can remove chunks, coalesce adjacent chunks,
    or shrink chunk payloads. Every candidate is rebuilt with canonical framing so size
    fields remain consistent. Invalid/non-canonical input is rejected rather than fixed.
    """
    mode, chunks = _parse_case(raw)
    seen: set[bytes] = set()

    def emit(candidate_chunks: tuple[bytes, ...]) -> Iterator[bytes]:
        candidate = _encode_case(mode, candidate_chunks)
        if len(candidate) < len(raw) and candidate not in seen:
            seen.add(candidate)
            yield candidate

    for index in range(len(chunks)):
        yield from emit(chunks[:index] + chunks[index + 1 :])

    for index in range(len(chunks) - 1):
        merged = chunks[index] + chunks[index + 1]
        yield from emit(chunks[:index] + (merged,) + chunks[index + 2 :])

    for index, chunk in enumerate(chunks):
        if not chunk:
            continue
        reductions = (b"",)
        if len(chunk) > 1:
            reductions += (chunk[: len(chunk) // 2], chunk[-1:])
        for reduced in reductions:
            candidate_chunks = list(chunks)
            candidate_chunks[index] = reduced
            yield from emit(tuple(candidate_chunks))
