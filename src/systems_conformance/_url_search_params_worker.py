from __future__ import annotations

import argparse
import json
import platform
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from urllib.parse import urlencode

_APPEND = 1
_SET = 2
_DELETE = 3
_SORT = 4


class RequestError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class Operation:
    opcode: int
    key: str | None = None
    value: str | None = None


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("value must be positive")
    return parsed


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--max-initial-pairs", type=_positive_int, required=True)
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
    max_field_bytes: int,
) -> tuple[str, int]:
    length, offset = _read_u32(raw, offset)
    if length > max_field_bytes:
        raise RequestError("field exceeds max_field_bytes")
    end = offset + length
    if end > len(raw):
        raise RequestError("field length exceeds request framing")
    return raw[offset:end].decode("utf-8", errors="strict"), end


def _decode_request(
    raw: bytes,
    *,
    max_initial_pairs: int,
    max_operations: int,
    max_field_bytes: int,
) -> tuple[list[tuple[str, str]], list[Operation]]:
    pair_count, offset = _read_u32(raw, 0)
    if pair_count > max_initial_pairs:
        raise RequestError("initial pair count exceeds max_initial_pairs")

    pairs: list[tuple[str, str]] = []
    for _ in range(pair_count):
        key, offset = _read_field(
            raw,
            offset,
            max_field_bytes=max_field_bytes,
        )
        value, offset = _read_field(
            raw,
            offset,
            max_field_bytes=max_field_bytes,
        )
        pairs.append((key, value))

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
            key, offset = _read_field(
                raw,
                offset,
                max_field_bytes=max_field_bytes,
            )
            value, offset = _read_field(
                raw,
                offset,
                max_field_bytes=max_field_bytes,
            )
            operations.append(Operation(opcode=opcode, key=key, value=value))
        elif opcode == _DELETE:
            key, offset = _read_field(
                raw,
                offset,
                max_field_bytes=max_field_bytes,
            )
            operations.append(Operation(opcode=opcode, key=key))
        elif opcode == _SORT:
            operations.append(Operation(opcode=opcode))
        else:
            raise RequestError("unsupported operation opcode")

    if offset != len(raw):
        raise RequestError("request contains trailing bytes")
    return pairs, operations


def _set_pair(pairs: list[tuple[str, str]], key: str, value: str) -> None:
    first_index: int | None = None
    retained: list[tuple[str, str]] = []

    for existing_key, existing_value in pairs:
        if existing_key != key:
            retained.append((existing_key, existing_value))
            continue
        if first_index is None:
            first_index = len(retained)
            retained.append((key, value))

    if first_index is None:
        retained.append((key, value))
    pairs[:] = retained


def _apply_operations(
    pairs: list[tuple[str, str]],
    operations: list[Operation],
) -> None:
    for operation in operations:
        if operation.opcode == _APPEND:
            assert operation.key is not None
            assert operation.value is not None
            pairs.append((operation.key, operation.value))
        elif operation.opcode == _SET:
            assert operation.key is not None
            assert operation.value is not None
            _set_pair(pairs, operation.key, operation.value)
        elif operation.opcode == _DELETE:
            assert operation.key is not None
            pairs[:] = [pair for pair in pairs if pair[0] != operation.key]
        elif operation.opcode == _SORT:
            pairs.sort(key=lambda pair: pair[0])
        else:
            raise AssertionError(f"unhandled operation opcode: {operation.opcode}")


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    if not _runtime_identity_matches(args):
        sys.stderr.write("url_search_params_runtime_identity_mismatch\n")
        return 3

    raw = sys.stdin.buffer.read()
    try:
        pairs, operations = _decode_request(
            raw,
            max_initial_pairs=args.max_initial_pairs,
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
        _apply_operations(pairs, operations)
        output = _encode_result(
            {
                "ok": True,
                "pairs": pairs,
                "query": urlencode(
                    pairs,
                    doseq=False,
                    encoding="utf-8",
                    errors="strict",
                ),
            }
        )

    sys.stdout.buffer.write(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
