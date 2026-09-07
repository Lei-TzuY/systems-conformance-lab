from __future__ import annotations

import json

import pytest

from systems_conformance import DifferentialHarness, SQLiteTransactionTarget
from systems_conformance._sqlite_transaction_bounded_worker import _validate_json_depth
from systems_conformance._sqlite_transaction_worker import ProtocolError


def _request() -> bytes:
    return json.dumps(
        {
            "setup": [],
            "transaction": [{"sql": "SELECT ?", "params": [1]}],
            "observe": {"sql": "SELECT '[{'", "params": []},
        },
        separators=(",", ":"),
    ).encode()


def _execute(case: bytes, *, max_json_depth: int):
    return SQLiteTransactionTarget(max_json_depth=max_json_depth).as_command_target().execute(
        case,
        timeout_seconds=2.0,
        max_output_bytes=4096,
        max_total_output_bytes=8192,
    )


def test_json_depth_preflight_ignores_delimiters_inside_strings() -> None:
    _validate_json_depth(b'{"value":"[[[{{{\\\""}', max_json_depth=1)


def test_json_depth_preflight_rejects_structural_nesting_over_budget() -> None:
    with pytest.raises(ProtocolError, match="request exceeds max_json_depth: 2"):
        _validate_json_depth(b'{"value":[[]]}', max_json_depth=2)


@pytest.mark.parametrize("value", [0, True])
def test_transaction_target_rejects_invalid_json_depth_budget(value: object) -> None:
    with pytest.raises(ValueError, match="max_json_depth must be a positive integer"):
        SQLiteTransactionTarget(max_json_depth=value)  # type: ignore[arg-type]


def test_real_transaction_target_rejects_deep_json_before_parser() -> None:
    nested = b"[" * 40 + b"0" + b"]" * 40
    case = (
        b'{"setup":[],"transaction":[{"sql":"SELECT 1","params":'
        + nested
        + b'}],"observe":{"sql":"SELECT 1"}}'
    )

    result = _execute(case, max_json_depth=8)

    assert result.infrastructure_error is None
    assert result.exit_code == 2
    assert result.stdout.text == ""
    assert result.stderr.text.strip() == "protocol_error: request exceeds max_json_depth: 8"


def test_real_transaction_target_accepts_exact_valid_protocol_depth() -> None:
    result = _execute(_request(), max_json_depth=4)

    assert result.infrastructure_error is None
    assert result.exit_code == 0
    assert result.stderr.text == ""
    assert json.loads(result.stdout.text)["transaction"][0]["rows"] == [[1]]


def test_real_harness_observes_json_depth_budget_as_target_identity() -> None:
    harness = DifferentialHarness(
        candidate=SQLiteTransactionTarget(max_json_depth=4).as_command_target(),
        oracle=SQLiteTransactionTarget(max_json_depth=3).as_command_target(),
        timeout_seconds=2.0,
    )

    run = harness.evaluate(_request())

    assert run.candidate.infrastructure_error is None
    assert run.oracle.infrastructure_error is None
    assert run.candidate.exit_code == 0
    assert run.oracle.exit_code == 2
    assert run.oracle.stderr.text.strip() == "protocol_error: request exceeds max_json_depth: 3"
    assert run.comparison.classification == "product_mismatch"
    assert run.signature is not None
    assert run.signature.kind == "product_mismatch"
