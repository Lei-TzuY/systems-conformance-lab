from __future__ import annotations

import json

import pytest

from systems_conformance import DifferentialHarness
from systems_conformance.sqlite_adapter import SQLiteQueryTarget


def _request(
    *,
    setup: list[str],
    query: str,
    params: list[object] | None = None,
    fault: dict[str, object] | None = None,
) -> bytes:
    payload: dict[str, object] = {
        "setup": setup,
        "query": query,
        "params": [] if params is None else params,
    }
    if fault is not None:
        payload["fault"] = fault
    return json.dumps(payload, separators=(",", ":")).encode()


def _execute(case: bytes, *, target: SQLiteQueryTarget | None = None):
    sqlite_target = SQLiteQueryTarget() if target is None else target
    return sqlite_target.as_command_target().execute(
        case,
        timeout_seconds=2.0,
        max_output_bytes=4096,
        max_total_output_bytes=8192,
    )


def test_sqlite_target_returns_canonical_rows_and_blobs() -> None:
    result = _execute(
        _request(
            setup=[
                "CREATE TABLE items(id INTEGER PRIMARY KEY, name TEXT, payload BLOB)",
                "INSERT INTO items(name, payload) VALUES ('alpha', X'00ff')",
            ],
            query="SELECT id, name, payload FROM items ORDER BY id",
        )
    )

    assert result.infrastructure_error is None
    assert result.exit_code == 0
    assert result.stderr.text == ""
    assert json.loads(result.stdout.text) == {
        "columns": ["id", "name", "payload"],
        "rows": [[1, "alpha", {"$blob": "00ff"}]],
    }


def test_sqlite_target_rejects_attach_without_touching_host_files(tmp_path) -> None:
    result = _execute(
        _request(setup=[], query=f"ATTACH DATABASE '{tmp_path / 'escape.db'}' AS escaped")
    )

    assert result.infrastructure_error is None
    assert result.exit_code == 3
    assert result.stdout.text == ""
    assert result.stderr.text.startswith("sqlite_error: ")
    assert not (tmp_path / "escape.db").exists()


def test_sqlite_target_rejects_duplicate_json_fields() -> None:
    result = _execute(b'{"setup":[],"query":"SELECT 1","query":"SELECT 2"}')

    assert result.infrastructure_error is None
    assert result.exit_code == 2
    assert result.stdout.text == ""
    assert result.stderr.text.strip() == "protocol_error: duplicate JSON object field: query"


def test_sqlite_target_rejects_non_finite_json_constants() -> None:
    result = _execute(b'{"setup":[],"query":"SELECT ?","params":[NaN]}')

    assert result.infrastructure_error is None
    assert result.exit_code == 2
    assert result.stdout.text == ""
    assert result.stderr.text.strip() == (
        "protocol_error: non-finite JSON constant is not supported: NaN"
    )


def test_sqlite_target_rejects_float_overflow_to_infinity() -> None:
    result = _execute(b'{"setup":[],"query":"SELECT ?","params":[1e400]}')

    assert result.infrastructure_error is None
    assert result.exit_code == 2
    assert result.stdout.text == ""
    assert result.stderr.text.strip() == "protocol_error: floating params must be finite"


def test_sqlite_target_rejects_integer_outside_binding_range_without_traceback() -> None:
    result = _execute(_request(setup=[], query="SELECT ?", params=[1 << 63]))

    assert result.infrastructure_error is None
    assert result.exit_code == 2
    assert result.stdout.text == ""
    assert result.stderr.text.strip() == (
        "protocol_error: integer params must fit signed 64-bit SQLite range"
    )


def test_sqlite_fault_checkpoint_triggers_at_exact_setup_occurrence() -> None:
    case = _request(
        setup=[
            "CREATE TABLE items(v INTEGER)",
            "INSERT INTO items VALUES (1)",
            "INSERT INTO items VALUES (2)",
        ],
        query="SELECT COUNT(*) FROM items",
        fault={"operation": "setup", "occurrence": 1, "kind": "abort"},
    )

    result = _execute(case, target=SQLiteQueryTarget(enable_faults=True))

    assert result.infrastructure_error is None
    assert result.exit_code == 5
    assert result.stdout.text == ""
    assert result.stderr.text.strip() == "injected_fault: abort setup 1"


def test_sqlite_fault_checkpoint_is_not_triggered_past_last_occurrence() -> None:
    case = _request(
        setup=["CREATE TABLE items(v INTEGER)", "INSERT INTO items VALUES (1)"],
        query="SELECT COUNT(*) FROM items",
        fault={"operation": "setup", "occurrence": 2, "kind": "abort"},
    )

    result = _execute(case, target=SQLiteQueryTarget(enable_faults=True))

    assert result.infrastructure_error is None
    assert result.exit_code == 0
    assert json.loads(result.stdout.text) == {"columns": ["COUNT(*)"], "rows": [[1]]}


def test_sqlite_target_rejects_unsupported_fault_kind() -> None:
    result = _execute(
        _request(
            setup=[],
            query="SELECT 1",
            fault={"operation": "query", "occurrence": 0, "kind": "corrupt"},
        ),
        target=SQLiteQueryTarget(enable_faults=True),
    )

    assert result.infrastructure_error is None
    assert result.exit_code == 2
    assert result.stderr.text.strip() == "protocol_error: unsupported SQLite fault kind"


@pytest.mark.parametrize("max_vm_steps", [0, -1, True, 1.5, "10"])
def test_sqlite_target_rejects_invalid_vm_budgets(max_vm_steps: object) -> None:
    with pytest.raises(ValueError, match="max_vm_steps must be a positive integer or None"):
        SQLiteQueryTarget(max_vm_steps=max_vm_steps)  # type: ignore[arg-type]


def test_sqlite_vm_budget_allows_small_query_within_limit() -> None:
    result = _execute(
        _request(setup=[], query="SELECT 1"),
        target=SQLiteQueryTarget(max_vm_steps=100),
    )

    assert result.infrastructure_error is None
    assert result.exit_code == 0
    assert json.loads(result.stdout.text) == {"columns": ["1"], "rows": [[1]]}


def test_sqlite_vm_budget_interrupts_recursive_query_without_harness_timeout() -> None:
    case = _request(
        setup=[],
        query=(
            "WITH RECURSIVE cnt(x) AS ("
            "VALUES(1) UNION ALL SELECT x+1 FROM cnt WHERE x<1000000"
            ") SELECT max(x) FROM cnt"
        ),
    )

    result = _execute(case, target=SQLiteQueryTarget(max_vm_steps=100))

    assert result.infrastructure_error is None
    assert result.exit_code == 6
    assert result.stdout.text == ""
    assert result.stderr.text.strip() == "sqlite_vm_budget_exceeded: 100"


def test_strict_protocol_rejection_is_deterministic_across_real_targets() -> None:
    candidate = SQLiteQueryTarget(foreign_keys=True).as_command_target()
    oracle = SQLiteQueryTarget(foreign_keys=False).as_command_target()
    harness = DifferentialHarness(candidate=candidate, oracle=oracle, timeout_seconds=2.0)
    case = b'{"setup":[],"query":"SELECT ?","params":[Infinity]}'

    run = harness.evaluate(case)

    assert run.candidate.exit_code == 2
    assert run.oracle.exit_code == 2
    assert run.candidate.stderr.text == run.oracle.stderr.text
    assert run.comparison.classification == "match"
    assert run.signature is None


def test_real_sqlite_targets_produce_product_mismatch_for_configuration_difference() -> None:
    candidate = SQLiteQueryTarget(foreign_keys=True).as_command_target()
    oracle = SQLiteQueryTarget(foreign_keys=False).as_command_target()
    harness = DifferentialHarness(candidate=candidate, oracle=oracle, timeout_seconds=2.0)
    case = _request(
        setup=[
            "CREATE TABLE parent(id INTEGER PRIMARY KEY)",
            "CREATE TABLE child(parent_id INTEGER REFERENCES parent(id))",
            "INSERT INTO child(parent_id) VALUES (99)",
        ],
        query="SELECT parent_id FROM child",
    )

    run = harness.evaluate(case)

    assert run.candidate.exit_code == 3
    assert run.oracle.exit_code == 0
    assert run.comparison.classification == "product_mismatch"
    assert run.signature is not None
    assert run.signature.kind == "product_mismatch"


def test_real_differential_harness_observes_injected_sqlite_fault() -> None:
    candidate = SQLiteQueryTarget(enable_faults=True).as_command_target()
    oracle = SQLiteQueryTarget(enable_faults=False).as_command_target()
    harness = DifferentialHarness(candidate=candidate, oracle=oracle, timeout_seconds=2.0)
    case = _request(
        setup=["CREATE TABLE items(v INTEGER)", "INSERT INTO items VALUES (1)"],
        query="SELECT v FROM items",
        fault={"operation": "query", "occurrence": 0, "kind": "abort"},
    )

    run = harness.evaluate(case)

    assert run.candidate.infrastructure_error is None
    assert run.oracle.infrastructure_error is None
    assert run.candidate.exit_code == 5
    assert run.candidate.stderr.text.strip() == "injected_fault: abort query 0"
    assert run.oracle.exit_code == 0
    assert run.comparison.classification == "product_mismatch"
    assert run.signature is not None
    assert run.signature.kind == "product_mismatch"


def test_real_differential_harness_observes_sqlite_vm_budget() -> None:
    candidate = SQLiteQueryTarget(max_vm_steps=100).as_command_target()
    oracle = SQLiteQueryTarget(max_vm_steps=100000).as_command_target()
    harness = DifferentialHarness(candidate=candidate, oracle=oracle, timeout_seconds=2.0)
    case = _request(
        setup=[],
        query=(
            "WITH RECURSIVE cnt(x) AS ("
            "VALUES(1) UNION ALL SELECT x+1 FROM cnt WHERE x<1000"
            ") SELECT max(x) FROM cnt"
        ),
    )

    run = harness.evaluate(case)

    assert run.candidate.infrastructure_error is None
    assert run.oracle.infrastructure_error is None
    assert run.candidate.exit_code == 6
    assert run.candidate.stderr.text.strip() == "sqlite_vm_budget_exceeded: 100"
    assert run.oracle.exit_code == 0
    assert run.comparison.classification == "product_mismatch"
    assert run.signature is not None
    assert run.signature.kind == "product_mismatch"
