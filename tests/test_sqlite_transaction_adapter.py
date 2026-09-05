from __future__ import annotations

import json

import pytest

from systems_conformance import DifferentialHarness, SQLiteTransactionTarget


def _statement(sql: str, params: list[object] | None = None) -> dict[str, object]:
    return {"sql": sql, "params": [] if params is None else params}


def _request(
    *,
    setup: list[str],
    transaction: list[dict[str, object]],
    observe: dict[str, object],
    fault: dict[str, object] | None = None,
) -> bytes:
    payload: dict[str, object] = {
        "setup": setup,
        "transaction": transaction,
        "observe": observe,
    }
    if fault is not None:
        payload["fault"] = fault
    return json.dumps(payload, separators=(",", ":")).encode()


def _execute(case: bytes, *, target: SQLiteTransactionTarget | None = None):
    sqlite_target = SQLiteTransactionTarget() if target is None else target
    return sqlite_target.as_command_target().execute(
        case,
        timeout_seconds=2.0,
        max_output_bytes=4096,
        max_total_output_bytes=8192,
    )


def test_transaction_target_emits_step_transcript_and_committed_observation() -> None:
    result = _execute(
        _request(
            setup=["CREATE TABLE items(v INTEGER, payload BLOB)"],
            transaction=[
                _statement("INSERT INTO items VALUES (?, X'00ff')", [7]),
                _statement("SELECT v, payload FROM items ORDER BY v"),
            ],
            observe=_statement("SELECT v, payload FROM items ORDER BY v"),
        )
    )

    assert result.infrastructure_error is None
    assert result.exit_code == 0
    assert result.stderr.text == ""
    assert json.loads(result.stdout.text) == {
        "transaction": [
            {"columns": [], "rows": []},
            {"columns": ["v", "payload"], "rows": [[7, {"$blob": "00ff"}]]},
        ],
        "observation": {
            "columns": ["v", "payload"],
            "rows": [[7, {"$blob": "00ff"}]],
        },
    }


def test_transaction_target_rolls_back_before_observation() -> None:
    case = _request(
        setup=["CREATE TABLE items(v INTEGER)"],
        transaction=[_statement("INSERT INTO items VALUES (1)")],
        observe=_statement("SELECT v FROM items ORDER BY v"),
    )

    result = _execute(case, target=SQLiteTransactionTarget(finalize="rollback"))

    assert result.infrastructure_error is None
    assert result.exit_code == 0
    assert json.loads(result.stdout.text)["observation"] == {"columns": ["v"], "rows": []}


def test_transaction_target_rejects_input_transaction_control() -> None:
    result = _execute(
        _request(
            setup=["CREATE TABLE items(v INTEGER)"],
            transaction=[_statement("COMMIT")],
            observe=_statement("SELECT v FROM items"),
        )
    )

    assert result.infrastructure_error is None
    assert result.exit_code == 3
    assert result.stdout.text == ""
    assert result.stderr.text.startswith("sqlite_error: ")


def test_transaction_target_rejects_statement_count_over_budget() -> None:
    result = _execute(
        _request(
            setup=["CREATE TABLE items(v INTEGER)"],
            transaction=[_statement("INSERT INTO items VALUES (1)")],
            observe=_statement("SELECT v FROM items"),
        ),
        target=SQLiteTransactionTarget(max_statements=2),
    )

    assert result.infrastructure_error is None
    assert result.exit_code == 2
    assert result.stderr.text.strip() == "protocol_error: request exceeds max_statements: 2"


def test_transaction_target_rejects_attach_without_touching_host_files(tmp_path) -> None:
    escape = tmp_path / "escape.db"
    result = _execute(
        _request(
            setup=["CREATE TABLE items(v INTEGER)"],
            transaction=[_statement(f"ATTACH DATABASE '{escape}' AS escaped")],
            observe=_statement("SELECT v FROM items"),
        )
    )

    assert result.infrastructure_error is None
    assert result.exit_code == 3
    assert not escape.exists()


def test_transaction_target_rejects_duplicate_json_fields() -> None:
    result = _execute(
        b'{"setup":[],"transaction":[{"sql":"SELECT 1","sql":"SELECT 2"}],'
        b'"observe":{"sql":"SELECT 1"}}'
    )

    assert result.infrastructure_error is None
    assert result.exit_code == 2
    assert result.stderr.text.strip() == "protocol_error: duplicate JSON object field: sql"


def test_transaction_fault_hits_exact_second_transaction_checkpoint() -> None:
    result = _execute(
        _request(
            setup=["CREATE TABLE items(v INTEGER)"],
            transaction=[
                _statement("INSERT INTO items VALUES (1)"),
                _statement("INSERT INTO items VALUES (2)"),
            ],
            observe=_statement("SELECT v FROM items ORDER BY v"),
            fault={"operation": "transaction", "occurrence": 1, "kind": "abort"},
        ),
        target=SQLiteTransactionTarget(enable_faults=True),
    )

    assert result.infrastructure_error is None
    assert result.exit_code == 5
    assert result.stdout.text == ""
    assert result.stderr.text.strip() == "injected_fault: abort transaction 1"


def test_transaction_fault_disabled_keeps_request_semantics() -> None:
    result = _execute(
        _request(
            setup=["CREATE TABLE items(v INTEGER)"],
            transaction=[_statement("INSERT INTO items VALUES (1)")],
            observe=_statement("SELECT v FROM items"),
            fault={"operation": "finalize", "occurrence": 0, "kind": "abort"},
        ),
        target=SQLiteTransactionTarget(enable_faults=False),
    )

    assert result.infrastructure_error is None
    assert result.exit_code == 0
    assert json.loads(result.stdout.text)["observation"]["rows"] == [[1]]


def test_transaction_target_rejects_unknown_fault_operation() -> None:
    result = _execute(
        _request(
            setup=[],
            transaction=[_statement("SELECT 1")],
            observe=_statement("SELECT 1"),
            fault={"operation": "commit", "occurrence": 0, "kind": "abort"},
        ),
        target=SQLiteTransactionTarget(enable_faults=True),
    )

    assert result.infrastructure_error is None
    assert result.exit_code == 2
    assert result.stderr.text.strip() == (
        "protocol_error: fault operation must be setup, transaction, finalize, or observe"
    )


def test_transaction_target_rejects_non_bool_fault_flag() -> None:
    with pytest.raises(TypeError, match="enable_faults must be a bool"):
        SQLiteTransactionTarget(enable_faults=1)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"finalize": "other"}, "finalize must be 'commit' or 'rollback'"),
        ({"max_statements": 0}, "max_statements must be a positive integer"),
        ({"max_statements": True}, "max_statements must be a positive integer"),
        ({"max_vm_steps": 0}, "max_vm_steps must be a positive integer or None"),
    ],
)
def test_transaction_target_rejects_invalid_configuration(
    kwargs: dict[str, object], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        SQLiteTransactionTarget(**kwargs)  # type: ignore[arg-type]


def test_real_harness_distinguishes_commit_from_rollback_semantics() -> None:
    candidate = SQLiteTransactionTarget(finalize="commit").as_command_target()
    oracle = SQLiteTransactionTarget(finalize="rollback").as_command_target()
    harness = DifferentialHarness(candidate=candidate, oracle=oracle, timeout_seconds=2.0)
    case = _request(
        setup=["CREATE TABLE items(v INTEGER)"],
        transaction=[_statement("INSERT INTO items VALUES (42)")],
        observe=_statement("SELECT v FROM items ORDER BY v"),
    )

    run = harness.evaluate(case)

    assert run.candidate.infrastructure_error is None
    assert run.oracle.infrastructure_error is None
    assert run.candidate.exit_code == 0
    assert run.oracle.exit_code == 0
    assert json.loads(run.candidate.stdout.text)["observation"]["rows"] == [[42]]
    assert json.loads(run.oracle.stdout.text)["observation"]["rows"] == []
    assert run.comparison.classification == "product_mismatch"
    assert run.signature is not None
    assert run.signature.kind == "product_mismatch"


def test_real_harness_classifies_transaction_fault_as_product_mismatch() -> None:
    candidate = SQLiteTransactionTarget(enable_faults=True).as_command_target()
    oracle = SQLiteTransactionTarget(enable_faults=False).as_command_target()
    harness = DifferentialHarness(candidate=candidate, oracle=oracle, timeout_seconds=2.0)
    case = _request(
        setup=["CREATE TABLE items(v INTEGER)"],
        transaction=[_statement("INSERT INTO items VALUES (42)")],
        observe=_statement("SELECT v FROM items ORDER BY v"),
        fault={"operation": "finalize", "occurrence": 0, "kind": "abort"},
    )

    run = harness.evaluate(case)

    assert run.candidate.infrastructure_error is None
    assert run.oracle.infrastructure_error is None
    assert run.candidate.exit_code == 5
    assert run.oracle.exit_code == 0
    assert run.candidate.stderr.text.strip() == "injected_fault: abort finalize 0"
    assert json.loads(run.oracle.stdout.text)["observation"]["rows"] == [[42]]
    assert run.comparison.classification == "product_mismatch"
    assert run.signature is not None
    assert run.signature.kind == "product_mismatch"
