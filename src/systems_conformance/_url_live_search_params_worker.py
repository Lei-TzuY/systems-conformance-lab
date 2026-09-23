from __future__ import annotations

import argparse
import json
import platform
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

_APPEND = 1
_SET = 2
_DELETE = 3
_SORT = 4
_SET_SEARCH = 5


class RequestError(ValueError):
    pass


class FormDecodeError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class Operation:
    opcode: int
    key: str | None = None
    value: str | None = None


@dataclass(slots=True)
class URLState:
    scheme: str
    netloc: str
    path: str
    fragment: str
    raw_query: str
    pairs: list[tuple[str, str]]


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("value must be positive")
    return parsed


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--max-url-bytes", type=_positive_int, required=True)
    parser.add_argument("--max-operations", type=_positive_int, required=True)
    parser.add_argument("--max-field-bytes", type=_positive_int, required=True)
    parser.add_argument("--python-implementation", required=True)
    parser.add_argument("--python-version", required=True)
    return parser.parse_args(argv)


def _runtime_identity_matches(args: argparse.Namespace) -> bool:
    return (
        args.python_implementation == sys.implementation.name
        and args.python_version == platform.python_version()
    )


def _encode_result(value: dict[str, object]) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        + b"\n"
    )


def _read_u32(raw: bytes, offset: int) -> tuple[int, int]:
    end = offset + 4
    if end > len(raw):
        raise RequestError("request framing is truncated")
    return int.from_bytes(raw[offset:end], "big"), end


def _read_field(
    raw: bytes,
    offset: int,
    *,
    max_bytes: int,
) -> tuple[str, int]:
    length, offset = _read_u32(raw, offset)
    if length > max_bytes:
        raise RequestError("field exceeds configured byte ceiling")
    end = offset + length
    if end > len(raw):
        raise RequestError("field length exceeds request framing")
    return raw[offset:end].decode("utf-8", errors="strict"), end


def _decode_request(
    raw: bytes,
    *,
    max_url_bytes: int,
    max_operations: int,
    max_field_bytes: int,
) -> tuple[str, list[Operation]]:
    url, offset = _read_field(raw, 0, max_bytes=max_url_bytes)

    operation_count, offset = _read_u32(raw, offset)
    if operation_count > max_operations:
        raise RequestError("operation count exceeds max_operations")

    operations: list[Operation] = []
    for _ in range(operation_count):
        if offset >= len(raw):
            raise RequestError("operation framing is truncated")
        opcode = raw[offset]
        offset += 1

        if opcode in {_APPEND, _SET}:
            key, offset = _read_field(raw, offset, max_bytes=max_field_bytes)
            value, offset = _read_field(raw, offset, max_bytes=max_field_bytes)
            operations.append(Operation(opcode=opcode, key=key, value=value))
        elif opcode == _DELETE:
            key, offset = _read_field(raw, offset, max_bytes=max_field_bytes)
            operations.append(Operation(opcode=opcode, key=key))
        elif opcode == _SORT:
            operations.append(Operation(opcode=opcode))
        elif opcode == _SET_SEARCH:
            value, offset = _read_field(raw, offset, max_bytes=max_field_bytes)
            operations.append(Operation(opcode=opcode, value=value))
        else:
            raise RequestError("unsupported operation opcode")

    if offset != len(raw):
        raise RequestError("request contains trailing bytes")
    return url, operations


def _decode_query(query: str) -> list[tuple[str, str]]:
    try:
        return parse_qsl(
            query,
            keep_blank_values=True,
            strict_parsing=False,
            encoding="utf-8",
            errors="strict",
            separator="&",
        )
    except UnicodeDecodeError as exc:
        raise FormDecodeError("query percent-decoded UTF-8 is invalid") from exc


def _parse_http_url(text: str) -> URLState:
    parsed = urlsplit(text)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("unsupported URL scheme")
    if not parsed.hostname:
        raise ValueError("URL hostname is required")
    _ = parsed.port

    return URLState(
        scheme=parsed.scheme,
        netloc=parsed.netloc,
        path=parsed.path,
        fragment=parsed.fragment,
        raw_query=parsed.query,
        pairs=_decode_query(parsed.query),
    )


def _serialize_pairs(pairs: list[tuple[str, str]]) -> str:
    return urlencode(
        pairs,
        doseq=False,
        encoding="utf-8",
        errors="strict",
    )


def _set_pair(pairs: list[tuple[str, str]], key: str, value: str) -> None:
    retained: list[tuple[str, str]] = []
    replaced = False
    for existing_key, existing_value in pairs:
        if existing_key != key:
            retained.append((existing_key, existing_value))
        elif not replaced:
            retained.append((key, value))
            replaced = True
    if not replaced:
        retained.append((key, value))
    pairs[:] = retained


def _set_search(state: URLState, value: str) -> None:
    query = value[1:] if value.startswith("?") else value
    pairs = _decode_query(query)
    state.raw_query = query
    state.pairs[:] = pairs


def _apply_params_serialization(state: URLState) -> None:
    state.raw_query = _serialize_pairs(state.pairs)


def _snapshot(state: URLState) -> dict[str, object]:
    return {
        "href": urlunsplit(
            (
                state.scheme,
                state.netloc,
                state.path,
                state.raw_query,
                state.fragment,
            )
        ),
        "pairs": list(state.pairs),
        "query": _serialize_pairs(state.pairs),
        "search": f"?{state.raw_query}" if state.raw_query else "",
    }


def _run_model(url: str, operations: list[Operation]) -> dict[str, object]:
    state = _parse_http_url(url)
    states = [_snapshot(state)]

    for operation in operations:
        if operation.opcode == _APPEND:
            assert operation.key is not None
            assert operation.value is not None
            state.pairs.append((operation.key, operation.value))
            _apply_params_serialization(state)
        elif operation.opcode == _SET:
            assert operation.key is not None
            assert operation.value is not None
            _set_pair(state.pairs, operation.key, operation.value)
            _apply_params_serialization(state)
        elif operation.opcode == _DELETE:
            assert operation.key is not None
            state.pairs[:] = [pair for pair in state.pairs if pair[0] != operation.key]
            _apply_params_serialization(state)
        elif operation.opcode == _SORT:
            state.pairs.sort(key=lambda pair: pair[0])
            _apply_params_serialization(state)
        elif operation.opcode == _SET_SEARCH:
            assert operation.value is not None
            _set_search(state, operation.value)
        else:
            raise AssertionError(f"unhandled operation opcode: {operation.opcode}")
        states.append(_snapshot(state))

    return {
        "ok": True,
        "states": states,
    }


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    if not _runtime_identity_matches(args):
        sys.stderr.write("url_live_search_params_runtime_identity_mismatch\n")
        return 3

    raw = sys.stdin.buffer.read()
    try:
        url, operations = _decode_request(
            raw,
            max_url_bytes=args.max_url_bytes,
            max_operations=args.max_operations,
            max_field_bytes=args.max_field_bytes,
        )
    except UnicodeDecodeError:
        output = _encode_result(
            {
                "error": "unicode_decode_error",
                "ok": False,
            }
        )
    except RequestError:
        output = _encode_result(
            {
                "error": "request_error",
                "ok": False,
            }
        )
    else:
        try:
            value = _run_model(url, operations)
        except FormDecodeError:
            output = _encode_result(
                {
                    "error": "form_decode_error",
                    "ok": False,
                }
            )
        except (UnicodeError, ValueError):
            output = _encode_result(
                {
                    "error": "url_parse_error",
                    "ok": False,
                }
            )
        else:
            output = _encode_result(value)

    sys.stdout.buffer.write(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
