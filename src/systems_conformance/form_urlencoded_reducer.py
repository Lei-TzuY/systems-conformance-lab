from __future__ import annotations

from collections.abc import Iterator


def _parse_encode_frame(raw: bytes) -> tuple[tuple[str, str], ...]:
    """Parse one strict ordered-pair encode frame or fail closed."""
    if len(raw) < 4:
        raise ValueError("form encode frame is truncated")

    count = int.from_bytes(raw[:4], "big")
    if count > (len(raw) - 4) // 8:
        raise ValueError("form encode frame pair count exceeds available framing")

    offset = 4
    pairs: list[tuple[str, str]] = []
    try:
        for _ in range(count):
            key_length = int.from_bytes(raw[offset : offset + 4], "big")
            offset += 4
            key_end = offset + key_length
            if key_end > len(raw):
                raise ValueError("form encode key exceeds frame")
            key = raw[offset:key_end].decode("utf-8", errors="strict")
            offset = key_end

            if offset + 4 > len(raw):
                raise ValueError("form encode value length is truncated")
            value_length = int.from_bytes(raw[offset : offset + 4], "big")
            offset += 4
            value_end = offset + value_length
            if value_end > len(raw):
                raise ValueError("form encode value exceeds frame")
            value = raw[offset:value_end].decode("utf-8", errors="strict")
            offset = value_end
            pairs.append((key, value))
    except UnicodeDecodeError as exc:
        raise ValueError("form encode frame contains invalid UTF-8") from exc

    if offset != len(raw):
        raise ValueError("form encode frame has trailing bytes")
    return tuple(pairs)


def _encode_frame(pairs: tuple[tuple[str, str], ...]) -> bytes:
    parts = [len(pairs).to_bytes(4, "big")]
    for key, value in pairs:
        key_bytes = key.encode("utf-8")
        value_bytes = value.encode("utf-8")
        parts.extend(
            (
                len(key_bytes).to_bytes(4, "big"),
                key_bytes,
                len(value_bytes).to_bytes(4, "big"),
                value_bytes,
            )
        )
    return b"".join(parts)


def _string_reductions(value: str) -> Iterator[str]:
    if not value:
        return
    yield ""
    if len(value) > 1:
        yield value[: len(value) // 2]
        yield value[-1:]


def form_urlencoded_encode_reduction_candidates(raw: bytes) -> Iterator[bytes]:
    """Yield deterministic, unique, strictly smaller valid encode-frame candidates.

    The reducer understands only the binary ordered-pair protocol used by encode mode.
    Invalid framing and invalid UTF-8 are rejected instead of being normalized. Pair
    deletion preserves duplicate-key ordering; field reductions operate on Unicode code
    points and then rebuild all byte lengths, so every emitted candidate remains a
    complete protocol frame.
    """
    pairs = _parse_encode_frame(raw)
    seen: set[bytes] = set()

    def emit(candidate_pairs: tuple[tuple[str, str], ...]) -> Iterator[bytes]:
        candidate = _encode_frame(candidate_pairs)
        if len(candidate) < len(raw) and candidate not in seen:
            seen.add(candidate)
            yield candidate

    for index in range(len(pairs)):
        yield from emit(pairs[:index] + pairs[index + 1 :])

    for index, (key, value) in enumerate(pairs):
        for reduced_key in _string_reductions(key):
            candidate_pairs = list(pairs)
            candidate_pairs[index] = (reduced_key, value)
            yield from emit(tuple(candidate_pairs))
        for reduced_value in _string_reductions(value):
            candidate_pairs = list(pairs)
            candidate_pairs[index] = (key, reduced_value)
            yield from emit(tuple(candidate_pairs))
