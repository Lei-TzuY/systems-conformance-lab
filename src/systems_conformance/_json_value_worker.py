from __future__ import annotations

import argparse
import json
import math
import platform
import sys
from collections.abc import Sequence


class ValueBudgetError(ValueError):
    pass


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("value must be positive")
    return parsed


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--max-json-bytes", type=_positive_int, required=True)
    parser.add_argument("--max-depth", type=_positive_int, required=True)
    parser.add_argument("--max-nodes", type=_positive_int, required=True)
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
        ).encode("ascii")
        + b"\n"
    )


def _canonical_number(value: int | float) -> str:
    if isinstance(value, int):
        return str(value)
    if math.isnan(value):
        return "NaN"
    if math.isinf(value):
        return "Infinity" if value > 0 else "-Infinity"
    return json.dumps(value, ensure_ascii=True, separators=(",", ":"), allow_nan=False)


def _key_order(value: str) -> str:
    return json.dumps(value, ensure_ascii=True, separators=(",", ":"), allow_nan=False)


def _project_value(
    value: object,
    *,
    max_depth: int,
    max_nodes: int,
) -> object:
    nodes = 0

    def project(current: object, depth: int) -> object:
        nonlocal nodes
        if depth > max_depth:
            raise ValueBudgetError("JSON value exceeds max_depth")
        nodes += 1
        if nodes > max_nodes:
            raise ValueBudgetError("JSON value exceeds max_nodes")

        if current is None:
            return ["null"]
        if isinstance(current, bool):
            return ["bool", current]
        if isinstance(current, int | float):
            return ["number", _canonical_number(current)]
        if isinstance(current, str):
            return ["string", current]
        if isinstance(current, list):
            return [
                "array",
                [project(item, depth + 1) for item in current],
            ]
        if isinstance(current, dict):
            ordered = sorted(current.items(), key=lambda item: _key_order(item[0]))
            return [
                "object",
                [[key, project(item, depth + 1)] for key, item in ordered],
            ]
        raise TypeError(f"unsupported JSON value type: {type(current).__name__}")

    return project(value, 0)


def _run(raw: bytes, args: argparse.Namespace) -> dict[str, object]:
    if len(raw) > args.max_json_bytes:
        return {"error": "input_budget_error", "ok": False}

    try:
        text = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        return {"error": "unicode_decode_error", "ok": False}

    try:
        parsed = json.loads(text)
    except RecursionError:
        return {"error": "value_budget_error", "ok": False}
    except (json.JSONDecodeError, ValueError):
        return {"error": "json_parse_error", "ok": False}

    try:
        projected = _project_value(
            parsed,
            max_depth=args.max_depth,
            max_nodes=args.max_nodes,
        )
    except (RecursionError, ValueBudgetError):
        return {"error": "value_budget_error", "ok": False}

    return {"ok": True, "value": projected}


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    if not _runtime_identity_matches(args):
        sys.stderr.write("json_value_runtime_identity_mismatch\n")
        return 3

    raw = sys.stdin.buffer.read(args.max_json_bytes + 1)
    try:
        output = _encode_result(_run(raw, args))
    except (TypeError, UnicodeError, ValueError):
        sys.stderr.write("json_value_python_runtime_error\n")
        return 3

    sys.stdout.buffer.write(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
