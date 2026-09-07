from __future__ import annotations

import json

import pytest

from systems_conformance import DifferentialHarness
from systems_conformance.sqlite_adapter import SQLiteQueryTarget


def _execute(case: bytes, *, depth: int):
    return SQLiteQueryTarget(max_json_depth=depth).as_command_target().execute(
        case,
        timeout_seconds=2.0,
        max_output_bytes=4096,
        max_total_output_bytes=8192,
    )


def test_query_target_rejects_json_before_decoder_depth_is_exceeded() -> None:
    case = b"[" * 40 + b"0" + b"]" * 40

    result = _execute(case, depth=8)

    assert result.infrastructure_error is None
    assert result.exit_code == 2
    assert result.stdout.text == ""
    assert result.stderr.text.strip() == "protocol_error: request exceeds max_json_depth: 8"


def test_query_target_ignores_delimiters_inside_json_strings() -> None:
    case = json.dumps(
        {"setup": [], "query": "SELECT ?", "params": ["[[[{{{\\\"}}}]]]"]},
        separators=(",", ":"),
    ).encode()

    result = _execute(case, depth=2)

    assert result.infrastructure_error is None
    assert result.exit_code == 0
    assert json.loads(result.stdout.text)["rows"] == [["[[[{{{\\\"}}}]]]"]]


def test_query_target_rejects_invalid_json_depth_configuration() -> None:
    for value in (0, -1, True):
        with pytest.raises(ValueError, match="max_json_depth must be a positive integer"):
            SQLiteQueryTarget(max_json_depth=value)  # type: ignore[arg-type]


def test_real_harness_observes_query_json_depth_configuration() -> None:
    candidate = SQLiteQueryTarget(max_json_depth=2).as_command_target()
    oracle = SQLiteQueryTarget(max_json_depth=1).as_command_target()
    harness = DifferentialHarness(candidate=candidate, oracle=oracle, timeout_seconds=2.0)
    case = json.dumps(
        {"setup": [], "query": "SELECT ?", "params": [7]}, separators=(",", ":")
    ).encode()

    run = harness.evaluate(case)

    assert run.candidate.infrastructure_error is None
    assert run.oracle.infrastructure_error is None
    assert run.candidate.exit_code == 0
    assert json.loads(run.candidate.stdout.text)["rows"] == [[7]]
    assert run.oracle.exit_code == 2
    assert run.oracle.stderr.text.strip() == "protocol_error: request exceeds max_json_depth: 1"
    assert run.comparison.classification == "product_mismatch"
    assert run.signature is not None
    assert run.signature.kind == "product_mismatch"
