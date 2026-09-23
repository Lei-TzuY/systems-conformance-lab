from __future__ import annotations

import json
import platform
import shutil
import subprocess
import sys

import pytest

from systems_conformance import (
    CommandTarget,
    DifferentialHarness,
    JSONParseNodeTarget,
    JSONParseTarget,
    run_failure_discovery_campaign,
)
from systems_conformance.json_parser_adapter import MAX_CONFIGURED_JSON_DOCUMENT_BYTES


def _harness(*, max_document_bytes: int = 64 * 1024) -> DifferentialHarness:
    return DifferentialHarness(
        candidate=JSONParseNodeTarget(
            max_document_bytes=max_document_bytes
        ).as_command_target(),
        oracle=JSONParseTarget(max_document_bytes=max_document_bytes).as_command_target(),
        timeout_seconds=5.0,
        max_input_bytes=64 * 1024,
        max_output_bytes=256 * 1024,
        max_total_output_bytes=512 * 1024,
    )


def _payload(text: str) -> dict[str, object]:
    return json.loads(text)


@pytest.mark.parametrize(
    ("raw", "value"),
    [
        (b"null", None),
        (b"true", True),
        (b"123", 123),
        (b'"hello"', "hello"),
        (b'[1,"two",false,null]', [1, "two", False, None]),
        (b'{"b":2,"a":[1,true]}', {"a": [1, True], "b": 2}),
        ('{"text":"雪"}'.encode(), {"text": "雪"}),
    ],
)
def test_shared_json_subset_matches_node_and_python(raw: bytes, value: object) -> None:
    run = _harness().evaluate(raw)

    assert run.comparison.classification == "match"
    assert run.signature is None
    assert _payload(run.candidate.stdout.text) == {"ok": True, "value": value}


@pytest.mark.parametrize("raw", [b"", b"{", b"[1,]", b"undefined", b"\xef\xbb\xbf{}"])
def test_shared_parse_rejections_match(raw: bytes) -> None:
    run = _harness().evaluate(raw)

    assert run.comparison.classification == "match"
    assert run.signature is None
    assert _payload(run.candidate.stdout.text) == {
        "error": "json_parse_error",
        "ok": False,
    }


@pytest.mark.parametrize("raw", [b"\xff", b'"\x80"'])
def test_invalid_utf8_rejects_before_json_parser(raw: bytes) -> None:
    run = _harness().evaluate(raw)

    assert run.comparison.classification == "match"
    assert run.signature is None
    assert _payload(run.candidate.stdout.text) == {
        "error": "utf8_decode_error",
        "ok": False,
    }


def test_large_integer_precision_surfaces_product_mismatch() -> None:
    run = _harness().evaluate(b'{"n":9007199254740993}')

    assert run.comparison.classification == "product_mismatch"
    assert run.comparison.mismatches == ("stdout",)
    assert run.signature is not None
    assert run.signature.kind == "product_mismatch"
    assert _payload(run.candidate.stdout.text) == {
        "ok": True,
        "value": {"n": 9007199254740992},
    }
    assert _payload(run.oracle.stdout.text) == {
        "ok": True,
        "value": {"n": 9007199254740993},
    }


def test_python_nonstandard_nan_acceptance_surfaces_product_mismatch() -> None:
    run = _harness().evaluate(b"NaN")

    assert run.comparison.classification == "product_mismatch"
    assert _payload(run.candidate.stdout.text) == {
        "error": "json_parse_error",
        "ok": False,
    }
    assert _payload(run.oracle.stdout.text) == {
        "error": "non_finite_number",
        "ok": False,
    }


def test_overflowing_json_number_is_reported_without_null_projection() -> None:
    run = _harness().evaluate(b"1e400")

    assert run.comparison.classification == "match"
    assert run.signature is None
    assert _payload(run.candidate.stdout.text) == {
        "error": "non_finite_number",
        "ok": False,
    }


def test_target_level_document_budget_is_fail_closed() -> None:
    run = _harness(max_document_bytes=4).evaluate(b"null ")

    assert run.comparison.classification == "match"
    assert _payload(run.candidate.stdout.text) == {
        "error": "input_too_large",
        "ok": False,
    }


@pytest.mark.parametrize(
    "target",
    [
        pytest.param(JSONParseTarget(max_document_bytes=4), id="python"),
        pytest.param(JSONParseNodeTarget(max_document_bytes=4), id="node"),
    ],
)
def test_oversize_document_rejects_without_waiting_for_eof(target: object) -> None:
    command = target.as_command_target()  # type: ignore[union-attr]
    process = subprocess.Popen(
        command.argv,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        assert process.stdin is not None
        process.stdin.write(b"null ")
        process.stdin.flush()
        process.wait(timeout=5.0)

        assert process.stdout is not None
        assert process.stderr is not None
        assert _payload(process.stdout.read().decode()) == {
            "error": "input_too_large",
            "ok": False,
        }
        assert process.stderr.read() == b""
        assert process.returncode == 0
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5.0)
        if process.stdin is not None:
            process.stdin.close()


def test_discovery_publishes_and_replays_numeric_precision_divergence(tmp_path) -> None:
    harness = _harness()
    corpus = (b'{"n":1}', b'{"n":9007199254740993}')

    discovery = run_failure_discovery_campaign(
        cases=corpus.__getitem__,
        evaluate=harness.compare,
        max_evaluations=len(corpus),
        max_unique_failures=4,
    )

    assert discovery.evaluations == len(corpus)
    assert len(discovery.failures) == 1
    failure = discovery.failures[0]
    assert failure.evaluation_index == 1
    assert failure.signature.kind == "product_mismatch"
    assert failure.signature.dimensions == ("stdout",)

    repro = harness.write_repro(
        tmp_path / "json-parser-repro",
        input_bytes=failure.case,
        expected_signature=failure.signature,
        metadata={"domain": "json-parser"},
    )
    replay = harness.replay_repro(repro.path)
    assert replay.reproduced is True
    assert replay.run.signature == failure.signature
    assert replay.bundle.metadata["domain"] == "json-parser"


@pytest.mark.parametrize(
    "budget",
    [-1, MAX_CONFIGURED_JSON_DOCUMENT_BYTES + 1, True, 1.5, "1024"],
)
def test_targets_reject_invalid_document_budget(budget: object) -> None:
    expected = TypeError if isinstance(budget, (bool, float, str)) else ValueError
    with pytest.raises(expected):
        JSONParseTarget(max_document_bytes=budget)  # type: ignore[arg-type]
    with pytest.raises(expected):
        JSONParseNodeTarget(max_document_bytes=budget)  # type: ignore[arg-type]


def _execute_command(target: CommandTarget, case: bytes) -> object:
    return target.execute(
        case,
        timeout_seconds=5.0,
        max_output_bytes=4096,
        max_total_output_bytes=8192,
    )


def test_python_runtime_identity_is_bound_and_verified_before_input() -> None:
    target = JSONParseTarget()
    implementation, python_version = target.runtime_identity
    command = target.as_command_target()

    assert implementation == sys.implementation.name
    assert python_version == platform.python_version()
    argv = list(command.argv)
    argv[argv.index("--python-version") + 1] = "__drift__"
    result = _execute_command(CommandTarget(tuple(argv)), b"null")

    assert result.exit_code == 3
    assert result.stdout.text == ""
    assert result.stderr.text.strip() == "json_parser_runtime_identity_mismatch"


def test_node_runtime_identity_is_bound_and_verified_before_input() -> None:
    target = JSONParseNodeTarget()
    (node_version,) = target.runtime_identity
    command = target.as_command_target()
    expected = f"const EXPECTED_NODE_VERSION = {json.dumps(node_version)};"

    assert node_version.startswith("v")
    assert expected in command.argv[2]
    drifted_script = command.argv[2].replace(
        expected,
        'const EXPECTED_NODE_VERSION = "__drift__";',
        1,
    )
    result = _execute_command(
        CommandTarget((target.node_executable, "-e", drifted_script)),
        b"null",
    )

    assert result.exit_code == 3
    assert result.stdout.text == ""
    assert result.stderr.text.strip() == "json_parser_runtime_identity_mismatch"


def test_document_budget_and_runtime_identity_change_replay_context() -> None:
    baseline = JSONParseTarget(max_document_bytes=1024).as_command_target()
    changed_budget = JSONParseTarget(max_document_bytes=2048).as_command_target()
    argv = list(baseline.argv)
    argv[argv.index("--python-version") + 1] = "__different_python__"
    changed_runtime = CommandTarget(tuple(argv))

    baseline_context = DifferentialHarness(
        candidate=baseline,
        oracle=baseline,
    ).replay_context_sha256
    for changed in (changed_budget, changed_runtime):
        assert baseline_context != DifferentialHarness(
            candidate=changed,
            oracle=changed,
        ).replay_context_sha256


def test_node_target_requires_available_runtime() -> None:
    assert shutil.which("node") is not None
    with pytest.raises(ValueError, match="node_executable"):
        JSONParseNodeTarget(node_executable="")
    with pytest.raises(RuntimeError, match="Node runtime is required"):
        JSONParseNodeTarget(node_executable="__missing_conformance_node__")
