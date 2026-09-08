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


def _result_features(prefix: str, payload: Any) -> set[str]:
    features: set[str] = set()
    if not isinstance(payload, dict) or set(payload) != {"columns", "rows"}:
        features.add(f"{prefix}:invalid-shape")
        return features

    columns = payload["columns"]
    rows = payload["rows"]
    if not isinstance(columns, list) or not all(isinstance(column, str) for column in columns):
        features.add(f"{prefix}:invalid-columns")
        return features
    if not isinstance(rows, list) or not all(isinstance(row, list) for row in rows):
        features.add(f"{prefix}:invalid-rows")
        return features

    features.add(f"{prefix}:columns:{_count_bucket(len(columns))}")
    features.add(f"{prefix}:rows:{_count_bucket(len(rows))}")
    widths = {len(row) for row in rows}
    if widths:
        for width in sorted(widths):
            features.add(f"{prefix}:row-width:{_count_bucket(width)}")
    else:
        features.add(f"{prefix}:row-width:empty")
    for row in rows:
        for value in row:
            features.add(f"{prefix}:value-kind:{_result_value_kind(value)}")
    return features


def _successful_transcript_features(side: str, execution: ExecutionResult) -> set[str]:
    features: set[str] = set()
    if execution.stdout.truncated:
        features.add(f"{side}:transcript:truncated")
        return features
    try:
        payload = json.loads(execution.stdout.text)
    except json.JSONDecodeError:
        features.add(f"{side}:transcript:invalid-json")
        return features
    if not isinstance(payload, dict) or set(payload) != {"transaction", "observation"}:
        features.add(f"{side}:transcript:invalid-shape")
        return features

    transaction = payload["transaction"]
    if not isinstance(transaction, list):
        features.add(f"{side}:transaction:invalid-list")
    else:
        features.add(f"{side}:transaction:statements:{_count_bucket(len(transaction))}")
        for statement in transaction:
            features.update(_result_features(f"{side}:transaction:result", statement))

    features.update(_result_features(f"{side}:observation:result", payload["observation"]))
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
    if execution.infrastructure_error is not None or execution.timed_out:
        return features
    if execution.exit_code == 0:
        features.update(_successful_transcript_features(side, execution))
    else:
        features.add(f"{side}:stderr-kind:{_stderr_kind(execution.stderr.text)}")
    return features


def sqlite_transaction_feedback_features(run: DifferentialRun) -> frozenset[str]:
    """Return bounded structural feedback for one SQLite transaction differential run.

    Feedback captures execution classes and normalized transcript shape, never raw SQL,
    column names, result values, stderr text, timings, or output bytes. Transaction
    statement result features are intentionally position-independent so the vocabulary
    stays bounded by structural classes rather than program length.
    """

    features = {f"comparison:{run.comparison.classification}"}
    features.update(f"comparison:mismatch:{field}" for field in run.comparison.mismatches)
    features.update(_execution_features("candidate", run.candidate))
    features.update(_execution_features("oracle", run.oracle))
    return frozenset(features)


@dataclass(frozen=True, slots=True)
class SQLiteTransactionFeedbackEvaluator:
    """Adapt a real transaction DifferentialHarness to feedback-guided fuzz evaluation."""

    harness: DifferentialHarness

    def __call__(self, input_bytes: bytes) -> tuple[ComparisonResult, frozenset[str]]:
        run = self.harness.evaluate(input_bytes)
        return run.comparison, sqlite_transaction_feedback_features(run)
