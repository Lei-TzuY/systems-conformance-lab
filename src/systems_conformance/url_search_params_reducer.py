from __future__ import annotations

from dataclasses import dataclass

_APPEND = 1
_SET = 2
_DELETE = 3
_SORT = 4


@dataclass(frozen=True, slots=True)
class URLSearchParamsOperation:
    opcode: int
    fields: tuple[bytes, ...]


@dataclass(frozen=True, slots=True)
class URLSearchParamsRequest:
    pairs: tuple[tuple[bytes, bytes], ...]
    operations: tuple[URLSearchParamsOperation, ...]


def _read_u32(raw: bytes, offset: int) -> tuple[int, int]:
    end = offset + 4
    if end > len(raw):
        raise ValueError("truncated URLSearchParams request")
    return int.from_bytes(raw[offset:end], "big"), end


def _read_field(raw: bytes, offset: int) -> tuple[bytes, int]:
    size, offset = _read_u32(raw, offset)
    end = offset + size
    if end > len(raw):
        raise ValueError("truncated URLSearchParams field")
    return raw[offset:end], end


def parse_url_search_params_request(raw: bytes) -> URLSearchParamsRequest:
    """Parse the bounded binary URLSearchParams protocol without executing it."""
    pair_count, offset = _read_u32(raw, 0)
    pairs: list[tuple[bytes, bytes]] = []
    for _ in range(pair_count):
        key, offset = _read_field(raw, offset)
        value, offset = _read_field(raw, offset)
        pairs.append((key, value))

    operation_count, offset = _read_u32(raw, offset)
    operations: list[URLSearchParamsOperation] = []
    for _ in range(operation_count):
        if offset >= len(raw):
            raise ValueError("truncated URLSearchParams operation")
        opcode = raw[offset]
        offset += 1
        if opcode in (_APPEND, _SET):
            key, offset = _read_field(raw, offset)
            value, offset = _read_field(raw, offset)
            fields = (key, value)
        elif opcode == _DELETE:
            key, offset = _read_field(raw, offset)
            fields = (key,)
        elif opcode == _SORT:
            fields = ()
        else:
            raise ValueError("unknown URLSearchParams operation")
        operations.append(URLSearchParamsOperation(opcode, fields))

    if offset != len(raw):
        raise ValueError("trailing URLSearchParams request bytes")
    return URLSearchParamsRequest(tuple(pairs), tuple(operations))


def _field(value: bytes) -> bytes:
    return len(value).to_bytes(4, "big") + value


def encode_url_search_params_request(request: URLSearchParamsRequest) -> bytes:
    raw = bytearray(len(request.pairs).to_bytes(4, "big"))
    for key, value in request.pairs:
        raw += _field(key)
        raw += _field(value)
    raw += len(request.operations).to_bytes(4, "big")
    for operation in request.operations:
        raw.append(operation.opcode)
        for value in operation.fields:
            raw += _field(value)
    return bytes(raw)


def _field_reductions(value: bytes) -> tuple[bytes, ...]:
    if not value:
        return ()
    candidates = [b""]
    if len(value) > 1:
        candidates.extend((value[: len(value) // 2], value[len(value) // 2 :]))
    return tuple(dict.fromkeys(candidate for candidate in candidates if candidate != value))


def url_search_params_reduction_candidates(raw: bytes):
    """Yield deterministic, strictly smaller, structurally valid protocol cases.

    Malformed input is rejected rather than interpreted heuristically. Candidates first
    delete whole semantic records, then shrink individual raw fields while preserving
    all length/count framing. Raw fields intentionally remain bytes: invalid UTF-8 is a
    product input and must not be silently normalized by reducer infrastructure.
    """
    request = parse_url_search_params_request(raw)
    seen: set[bytes] = set()

    def emit(candidate: URLSearchParamsRequest):
        encoded = encode_url_search_params_request(candidate)
        if len(encoded) < len(raw) and encoded not in seen:
            seen.add(encoded)
            return encoded
        return None

    for index in range(len(request.operations)):
        candidate = emit(
            URLSearchParamsRequest(
                request.pairs,
                request.operations[:index] + request.operations[index + 1 :],
            )
        )
        if candidate is not None:
            yield candidate

    for index in range(len(request.pairs)):
        candidate = emit(
            URLSearchParamsRequest(
                request.pairs[:index] + request.pairs[index + 1 :],
                request.operations,
            )
        )
        if candidate is not None:
            yield candidate

    for pair_index, pair in enumerate(request.pairs):
        for field_index, value in enumerate(pair):
            for reduced in _field_reductions(value):
                changed_pair = list(pair)
                changed_pair[field_index] = reduced
                pairs = list(request.pairs)
                pairs[pair_index] = (changed_pair[0], changed_pair[1])
                candidate = emit(URLSearchParamsRequest(tuple(pairs), request.operations))
                if candidate is not None:
                    yield candidate

    for operation_index, operation in enumerate(request.operations):
        for field_index, value in enumerate(operation.fields):
            for reduced in _field_reductions(value):
                fields = list(operation.fields)
                fields[field_index] = reduced
                operations = list(request.operations)
                operations[operation_index] = URLSearchParamsOperation(
                    operation.opcode, tuple(fields)
                )
                candidate = emit(URLSearchParamsRequest(request.pairs, tuple(operations)))
                if candidate is not None:
                    yield candidate
