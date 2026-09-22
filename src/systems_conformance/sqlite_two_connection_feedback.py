from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from .comparator import ComparisonResult
from .harness import DifferentialHarness, DifferentialRun
from .model import ExecutionResult

_KNOWN_OPS = {
    "begin",
    "try_begin",
    "commit",
    "rollback",
    "execute",
    "try_execute",
    "query",
    "try_query",
}
_BUSY_ERRORS = {"SQLITE_BUSY", "SQLITE_BUSY_RECOVERY", "SQLITE_BUSY_SNAPSHOT"}


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
        "protocol_error",
        "result_error",
        "sqlite_error",
        "sqlite_scenario_error",
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


def _result_features(prefix: str, step: dict[str, Any]) -> set[str]:
    features: set[str] = set()
    columns = step.get("columns")
    rows = step.get("rows")
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
    if not isinstance(payload, dict) or set(payload) != {"steps"}:
        features.add(f"{side}:transcript:invalid-shape")
        return features

    steps = payload["steps"]
    if not isinstance(steps, list):
        features.add(f"{side}:transcript:invalid-steps")
        return features
    features.add(f"{side}:transcript:steps:{_count_bucket(len(steps))}")

    for step in steps:
        if not isinstance(step, dict):
            features.add(f"{side}:step:invalid")
            continue

        connection = step.get("connection")
        connection_kind = (
            connection if isinstance(connection, str) and connection in {"a", "b"} else "other"
        )
        features.add(f"{side}:step:connection:{connection_kind}")

        op = step.get("op")
        op_kind = op if isinstance(op, str) and op in _KNOWN_OPS else "other"
        features.add(f"{side}:step:op:{op_kind}")

        if op_kind in {"begin", "try_begin"}:
            mode = step.get("mode")
            mode_kind = (
                mode
                if isinstance(mode, str) and mode in {"deferred", "immediate", "exclusive"}
                else "other"
            )
            features.add(f"{side}:step:mode:{mode_kind}")

        if op_kind in {"try_begin", "try_execute", "try_query"}:
            ok = step.get("ok")
            if isinstance(ok, bool):
                features.add(f"{side}:try:ok:{int(ok)}")
                if not ok:
                    error = step.get("error")
                    error_kind = (
                        error if isinstance(error, str) and error in _BUSY_ERRORS else "other"
                    )
                    features.add(f"{side}:try:error:{error_kind}")
                    features.add(
                        f"{side}:try:error-code-present:{int(isinstance(step.get('error_code'), int))}"
                    )
            else:
                features.add(f"{side}:try:invalid-ok")

        if op_kind == "query" or (op_kind == "try_query" and step.get("ok") is True):
            features.update(_result_features(f"{side}:result", step))

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


def sqlite_two_connection_feedback_features(run: DifferentialRun) -> frozenset[str]:
    """Return bounded structural feedback for one two-connection SQLite run.

    Feedback captures execution classes, normalized scenario transcript structure,
    recognized busy outcomes, and result shape/value kinds. It deliberately excludes
    SQL text, column names, raw values, error codes, stderr text, timings, and output
    bytes so corpus growth reflects semantic structure rather than unbounded data.
    """

    features = {f"comparison:{run.comparison.classification}"}
    features.update(f"comparison:mismatch:{field}" for field in run.comparison.mismatches)
    features.update(_execution_features("candidate", run.candidate))
    features.update(_execution_features("oracle", run.oracle))
    return frozenset(features)


@dataclass(frozen=True, slots=True)
class SQLiteTwoConnectionFeedbackEvaluator:
    """Adapt a real two-connection DifferentialHarness to feedback-guided evaluation."""

    harness: DifferentialHarness

    def __call__(self, input_bytes: bytes) -> tuple[ComparisonResult, frozenset[str]]:
        run = self.harness.evaluate(input_bytes)
        return run.comparison, sqlite_two_connection_feedback_features(run)
