from __future__ import annotations

import json

import pytest

from systems_conformance import DifferentialHarness
from systems_conformance.sqlite_adapter import SQLiteQueryTarget


def _request(query: str) -> bytes:
    return json.dumps({"setup": [], "query": query, "params": []}, separators=(",", ":")).encode()


def _execute(case: bytes, target: SQLiteQueryTarget):
    return target.as_command_target().execute(
        case,
        timeout_seconds=2.0,
        max_output_bytes=4096,
        max_total_output_bytes=8192,
    )


@pytest.mark.parametrize("value", [0, -1, True, 1.5, "8"])
def test_sqlite_target_rejects_invalid_result_value_budgets(value: object) -> None:
    with pytest.raises(ValueError, match="max_result_value_bytes must be a positive integer"):
        SQLiteQueryTarget(max_result_value_bytes=value)  # type: ignore[arg-type]


def test_sqlite_result_value_budget_accepts_exact_utf8_boundary() -> None:
    result = _execute(_request("SELECT 'éé'"), SQLiteQueryTarget(max_result_value_bytes=4))

    assert result.infrastructure_error is None
    assert result.exit_code == 0
    assert json.loads(result.stdout.text)["rows"] == [["éé"]]


def test_sqlite_result_value_budget_rejects_before_blob_hex_expansion() -> None:
    result = _execute(_request("SELECT zeroblob(5)"), SQLiteQueryTarget(max_result_value_bytes=4))

    assert result.infrastructure_error is None
    assert result.exit_code == 4
    assert result.stdout.text == ""
    assert result.stderr.text.strip() == (
        "result_error: result value exceeds max_result_value_bytes: 4"
    )


def test_result_value_budget_is_part_of_replay_identity() -> None:
    low = SQLiteQueryTarget(max_result_value_bytes=4).as_command_target()
    high = SQLiteQueryTarget(max_result_value_bytes=5).as_command_target()

    assert low.argv != high.argv
    assert "--max-result-value-bytes" in low.argv


def test_real_harness_observes_result_value_budget_as_product_mismatch() -> None:
    candidate = SQLiteQueryTarget(max_result_value_bytes=4).as_command_target()
    oracle = SQLiteQueryTarget(max_result_value_bytes=5).as_command_target()
    harness = DifferentialHarness(candidate=candidate, oracle=oracle, timeout_seconds=2.0)

    run = harness.evaluate(_request("SELECT zeroblob(5)"))

    assert run.candidate.infrastructure_error is None
    assert run.oracle.infrastructure_error is None
    assert run.candidate.exit_code == 4
    assert run.oracle.exit_code == 0
    assert run.comparison.classification == "product_mismatch"
    assert run.signature is not None
    assert run.signature.kind == "product_mismatch"
