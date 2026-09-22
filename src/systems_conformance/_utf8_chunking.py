from __future__ import annotations

MAX_CHUNK_PATTERN_LENGTH = 64


def validate_chunk_pattern(value: object) -> tuple[int, ...]:
    """Return one validated immutable irregular chunk pattern.

    None represents the legacy fixed-size segmentation policy. Explicit patterns must
    be non-empty tuples of positive integers and are length-bounded so argv/config
    construction remains finite before any input bytes are processed.
    """

    if value is None:
        return ()
    if not isinstance(value, tuple):
        raise ValueError("chunk_pattern must be a tuple of positive integers")
    if not value:
        raise ValueError("chunk_pattern must be non-empty")
    if len(value) > MAX_CHUNK_PATTERN_LENGTH:
        raise ValueError(
            f"chunk_pattern must contain at most {MAX_CHUNK_PATTERN_LENGTH} entries"
        )
    for item in value:
        if isinstance(item, bool) or not isinstance(item, int) or item <= 0:
            raise ValueError("chunk_pattern entries must be positive integers")
    return value


def encode_chunk_pattern(value: object) -> str:
    """Serialize a validated pattern for process argv."""

    return ",".join(str(item) for item in validate_chunk_pattern(value))


def parse_chunk_pattern(value: str) -> tuple[int, ...]:
    """Parse the argv representation used by the Python worker."""

    if value == "":
        return ()
    try:
        parsed = tuple(int(item) for item in value.split(","))
    except ValueError as exc:
        raise ValueError("chunk_pattern entries must be positive integers") from exc
    return validate_chunk_pattern(parsed)
