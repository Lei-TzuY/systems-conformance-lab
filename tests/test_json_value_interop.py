from __future__ import annotations

import json
import platform
import shutil
import sys

import pytest

from systems_conformance import (
    CommandTarget,
    DifferentialHarness,
    JSONNodeValueTarget,
    JSONValueTarget,
    run_failure_discovery_campaign,
)


def _harness(
    *,
    max_json_bytes: int = 16 * 1024,
    max_depth: int = 64,
    max_nodes: int = 4096,
) -> DifferentialHarness:
    return DifferentialHarness(
        candidate=JSONNodeValueTarget(
            max_json_bytes=max_json_bytes,
            max_depth=max_depth,
            max_nodes=max_nodes,
        ).as_command_target(),
        oracle=JSONValueTarget(
            max_json_bytes=max_json_bytes,
            max_depth=max_depth,
            max_nodes=max_nodes,
        ).as_command_target(),
        timeout_seconds=5.0,
        max_input_bytes=64 * 1024,
        max_output_bytes=128 * 1024,
        max_total_output_bytes=256 * 1024,
    )


def _payload(text: str) -> dict[str, object]:
    return json.loads(text)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (b"null", {"ok": True, "value": ["null"]}),
        (b"true", {"ok": True, "value": ["bool", True]}),
        (b"1", {"ok": True, "value": ["number", "1"]}),
        (b"1e400", {"ok": True, "value": ["number", "Infinity"]}),
        (
            b'{"2":"b","1":"a","x":0}',
            {
                "ok": True,
                "value": [
                    "object",
                    [
                        ["1", ["string", "a"]],
                        ["2", ["string", "b"]],
                        ["x", ["number", "0"]],
                    ],
                ],
            },
        ),
        (
            b'{"a":[true,null,"x"],"a":[false,2]}',
            {
                "ok": True,
                "value": [
                    "object",
                    [
                        [
                            "a",
                            ["array", [["bool", False], ["number", "2"]]],
                        ]
                    ],
                ],
            },
        ),
        (b'"\\ud800"', {"ok": True, "value": ["string", "\ud800"]}),
    ],
)
def test_node_matches_python_for_shared_json_value_subset(
    raw: bytes,
    expected: dict[str, object],
) -> None:
    run = _harness().evaluate(raw)

    assert run.comparison.classification == "match"
    assert run.signature is None
    assert run.candidate.exit_code == 0
    assert run.oracle.exit_code == 0
    assert _payload(run.candidate.stdout.text) == expected


@pytest.mark.parametrize(
    "raw",
    [
        b"\xff",
        b'"\xc3("',
        b'"\xe2\x82"',
    ],
)
def test_invalid_utf8_rejects_before_json_parsing(raw: bytes) -> None:
    run = _harness().evaluate(raw)

    assert run.comparison.classification == "match"
    assert run.signature is None
    assert _payload(run.candidate.stdout.text) == {
        "error": "unicode_decode_error",
        "ok": False,
    }


@pytest.mark.parametrize(
    "raw",
    [
        b"",
        b"[1,]",
        b"{'a':1}",
        b'{"a":1} trailing',
        b"\xef\xbb\xbfnull",
    ],
)
def test_shared_invalid_json_rejects_canonically(raw: bytes) -> None:
    run = _harness().evaluate(raw)

    assert run.comparison.classification == "match"
    assert run.signature is None
    assert _payload(run.candidate.stdout.text) == {
        "error": "json_parse_error",
        "ok": False,
    }


@pytest.mark.parametrize(
    "raw",
    [
        b"1.0",
        b"-0.0",
        b"9007199254740993",
        b"NaN",
        b"Infinity",
        b"-Infinity",
    ],
)
def test_native_json_number_policies_surface_stable_product_mismatches(raw: bytes) -> None:
    run = _harness().evaluate(raw)

    assert run.comparison.classification == "product_mismatch"
    assert run.comparison.mismatches == ("stdout",)
    assert run.signature is not None
    assert run.signature.kind == "product_mismatch"
    assert run.signature.dimensions == ("stdout",)


def test_object_observation_order_is_language_neutral() -> None:
    raw = b'{"10":"ten","2":"two","a":"letter"}'
    run = _harness().evaluate(raw)

    assert run.comparison.classification == "match"
    assert _payload(run.candidate.stdout.text)["value"] == [
        "object",
        [
            ["10", ["string", "ten"]],
            ["2", ["string", "two"]],
            ["a", ["string", "letter"]],
        ],
    ]


@pytest.mark.parametrize(
    ("max_depth", "max_nodes", "raw"),
    [
        (1, 64, b"[[0]]"),
        (64, 2, b"[0,1]"),
        (64, 4096, b"[" * 1100 + b"0" + b"]" * 1100),
    ],
)
def test_structural_value_budgets_fail_closed_on_both_runtimes(
    max_depth: int,
    max_nodes: int,
    raw: bytes,
) -> None:
    run = _harness(max_depth=max_depth, max_nodes=max_nodes).evaluate(raw)

    assert run.comparison.classification == "match"
    assert run.signature is None
    assert _payload(run.candidate.stdout.text) == {
        "error": "value_budget_error",
        "ok": False,
    }


def test_target_json_byte_budget_is_enforced_inside_both_workers() -> None:
    run = _harness(max_json_bytes=4).evaluate(b'"abcd"')

    assert run.comparison.classification == "match"
    assert run.signature is None
    assert _payload(run.candidate.stdout.text) == {
        "error": "input_budget_error",
        "ok": False,
    }


def test_discovery_witness_publishes_and_replays_json_precision_divergence(tmp_path) -> None:
    harness = _harness()
    corpus = (
        b'{"a":1}',
        b"9007199254740993",
    )

    discovery = run_failure_discovery_campaign(
        cases=corpus.__getitem__,
        evaluate=harness.compare,
        max_evaluations=len(corpus),
        max_unique_failures=4,
    )

    assert discovery.evaluations == len(corpus)
    assert discovery.exhausted_budget is True
    assert discovery.reached_failure_limit is False
    assert len(discovery.failures) == 1
    failure = discovery.failures[0]
    assert failure.evaluation_index == 1
    assert failure.case == corpus[1]
    assert failure.signature.kind == "product_mismatch"
    assert failure.signature.dimensions == ("stdout",)

    repro = harness.write_repro(
        tmp_path / "json-value-repro",
        input_bytes=failure.case,
        expected_signature=failure.signature,
        metadata={"domain": "json-value-semantics"},
    )
    assert repro.input_path.read_bytes() == failure.case

    replay = harness.replay_repro(repro.path)
    assert replay.reproduced is True
    assert replay.run.signature == failure.signature
    assert replay.bundle.metadata["domain"] == "json-value-semantics"


def _execute_command(target: CommandTarget, case: bytes = b"null"):
    return target.execute(
        case,
        timeout_seconds=5.0,
        max_input_bytes=64 * 1024,
        max_output_bytes=4096,
        max_total_output_bytes=8192,
    )


def test_python_runtime_identity_is_bound_and_verified_before_input() -> None:
    target = JSONValueTarget()
    implementation, python_version = target.runtime_identity
    command = target.as_command_target()

    assert implementation == sys.implementation.name
    assert python_version == platform.python_version()
    assert command.argv[-4:] == (
        "--python-implementation",
        implementation,
        "--python-version",
        python_version,
    )

    drifted_argv = list(command.argv)
    drifted_argv[drifted_argv.index("--python-version") + 1] = "__drift__"
    result = _execute_command(CommandTarget(tuple(drifted_argv)))

    assert result.exit_code == 3
    assert result.stdout.text == ""
    assert result.stderr.text.strip() == "json_value_runtime_identity_mismatch"


def test_node_runtime_identity_is_bound_and_verified_before_input() -> None:
    target = JSONNodeValueTarget()
    (node_version,) = target.runtime_identity
    command = target.as_command_target()

    assert node_version.startswith("v")
    expected = f"const EXPECTED_NODE_VERSION = {json.dumps(node_version)};"
    assert expected in command.argv[2]

    drifted_script = command.argv[2].replace(
        expected,
        'const EXPECTED_NODE_VERSION = "__drift__";',
        1,
    )
    assert drifted_script != command.argv[2]
    result = _execute_command(CommandTarget((target.node_executable, "-e", drifted_script)))

    assert result.exit_code == 3
    assert result.stdout.text == ""
    assert result.stderr.text.strip() == "json_value_runtime_identity_mismatch"


def test_structural_configuration_changes_replay_context() -> None:
    baseline_target = JSONValueTarget(max_depth=32, max_nodes=1024).as_command_target()
    changed_target = JSONValueTarget(max_depth=33, max_nodes=1024).as_command_target()
    baseline = DifferentialHarness(candidate=baseline_target, oracle=baseline_target)
    changed = DifferentialHarness(candidate=changed_target, oracle=changed_target)

    assert baseline.replay_context_sha256 != changed.replay_context_sha256


@pytest.mark.parametrize("name", ["max_json_bytes", "max_depth", "max_nodes"])
def test_target_structural_budgets_require_positive_integers(name: str) -> None:
    kwargs = {name: 0}
    with pytest.raises(ValueError, match=name):
        JSONValueTarget(**kwargs)
    with pytest.raises(ValueError, match=name):
        JSONNodeValueTarget(**kwargs)

    kwargs[name] = True
    with pytest.raises(ValueError, match=name):
        JSONValueTarget(**kwargs)
    with pytest.raises(ValueError, match=name):
        JSONNodeValueTarget(**kwargs)


def test_node_target_requires_available_runtime() -> None:
    assert shutil.which("node") is not None

    with pytest.raises(ValueError, match="node_executable"):
        JSONNodeValueTarget(node_executable="")
    with pytest.raises(RuntimeError, match="Node runtime is required"):
        JSONNodeValueTarget(node_executable="__missing_conformance_node__")
