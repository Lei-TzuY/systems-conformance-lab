from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from .comparator import ComparisonResult
from .harness import DifferentialHarness, DifferentialRun
from .model import ExecutionResult


def _count_bucket(value: int) -> str:
    if value <= 0:
        return "0"
    if value == 1:
        return "1"
    lower = 1 << (value.bit_length() - 1)
    if lower == value:
        return str(value)
    return f"{lower + 1}-{(lower << 1) - 1}"


def _stderr_kind(text: str) -> str:
    first_line = text.splitlines()[0] if text else ""
    prefix, separator, _rest = first_line.partition(":")
    if separator and prefix in {
        "injected_fault",
        "protocol_error",
        "result_error",
        "sqlite_error",
        "sqlite_vm_budget_exceeded",
    }:
        return prefix
    return "other" if first_line else "empty"


def _result_value_kind(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    if isinstance(value, str):
        return "text"
    if isinstance(value, dict) and set(value) == {"$blob"} and isinstance(value["$blob"], str):
        return "blob"
    return "other"


def _successful_result_features(side: str, execution: ExecutionResult) -> set[str]:
    features: set[str] = set()
    if execution.stdout.truncated:
        features.add(f"{side}:result:truncated")
        return features
    try:
        payload = json.loads(execution.stdout.text)
    except json.JSONDecodeError:
        features.add(f"{side}:result:invalid-json")
        return features
    if not isinstance(payload, dict) or set(payload) != {"columns", "rows"}:
        features.add(f"{side}:result:invalid-shape")
        return features

    columns = payload["columns"]
    rows = payload["rows"]
    if not isinstance(columns, list) or not all(isinstance(column, str) for column in columns):
        features.add(f"{side}:result:invalid-columns")
        return features
    if not isinstance(rows, list) or not all(isinstance(row, list) for row in rows):
        features.add(f"{side}:result:invalid-rows")
        return features

    features.add(f"{side}:result:columns:{_count_bucket(len(columns))}")
    features.add(f"{side}:result:rows:{_count_bucket(len(rows))}")
    widths = {len(row) for row in rows}
    if widths:
        for width in sorted(widths):
            features.add(f"{side}:result:row-width:{_count_bucket(width)}")
    else:
        features.add(f"{side}:result:row-width:empty")
    for row in rows:
        for value in row:
            features.add(f"{side}:result:value-kind:{_result_value_kind(value)}")
    return features


def _execution_features(side: str, execution: ExecutionResult) -> set[str]:
    features = {
        f"{side}:timed-out:{int(execution.timed_out)}",
        f"{side}:stdout-truncated:{int(execution.stdout.truncated)}",
        f"{side}:stderr-truncated:{int(execution.stderr.truncated)}",
        f"{side}:infrastructure-error:{int(execution.infrastructure_error is not None)}",
    }
    if execution.exit_code is None:
        features.add(f"{side}:exit:none")
    else:
        features.add(f"{side}:exit:{execution.exit_code}")
    if execution.signal is not None:
        features.add(f"{side}:signal:{execution.signal}")
    if execution.infrastructure_error is not None:
        return features
    if execution.timed_out:
        return features
    if execution.exit_code == 0:
        features.update(_successful_result_features(side, execution))
    else:
        features.add(f"{side}:stderr-kind:{_stderr_kind(execution.stderr.text)}")
    return features


def sqlite_query_feedback_features(run: DifferentialRun) -> frozenset[str]:
    """Return bounded structural feedback for one SQLite query differential run.

    Features deliberately describe execution classes and result shape rather than raw
    SQL values, column names, stderr messages, timings, or output bytes. This keeps the
    feedback vocabulary stable and useful for deterministic corpus admission without
    turning every distinct result value into synthetic coverage.
    """

    features = {f"comparison:{run.comparison.classification}"}
    features.update(f"comparison:mismatch:{field}" for field in run.comparison.mismatches)
    features.update(_execution_features("candidate", run.candidate))
    features.update(_execution_features("oracle", run.oracle))
    return frozenset(features)


@dataclass(frozen=True, slots=True)
class SQLiteQueryFeedbackEvaluator:
    """Callable adapter from DifferentialHarness to feedback-guided fuzz evaluation."""

    harness: DifferentialHarness

    def __call__(self, input_bytes: bytes) -> tuple[ComparisonResult, frozenset[str]]:
        run = self.harness.evaluate(input_bytes)
        return run.comparison, sqlite_query_feedback_features(run)
