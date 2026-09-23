from __future__ import annotations

import json
import platform
import shutil
import sys

import pytest

from systems_conformance import (
    CommandTarget,
    DifferentialHarness,
    URLNodeQueryCanonicalizationTarget,
    URLQueryCanonicalizationTarget,
    run_failure_discovery_campaign,
)


def _harness() -> DifferentialHarness:
    return DifferentialHarness(
        candidate=URLNodeQueryCanonicalizationTarget().as_command_target(),
        oracle=URLQueryCanonicalizationTarget().as_command_target(),
        timeout_seconds=5.0,
        max_input_bytes=64 * 1024,
        max_output_bytes=512 * 1024,
        max_total_output_bytes=1024 * 1024,
    )


def _payload(text: str) -> dict[str, object]:
    return json.loads(text)


@pytest.mark.parametrize(
    ("raw", "expected_query", "expected_pairs", "expected_url"),
    [
        (
            b"https://example.com/path?a=1&b=two+words#frag",
            "a=1&b=two+words",
            [["a", "1"], ["b", "two words"]],
            "https://example.com/path?a=1&b=two+words#frag",
        ),
        (
            b"https://example.com/path?a=1&a=2",
            "a=1&a=2",
            [["a", "1"], ["a", "2"]],
            "https://example.com/path?a=1&a=2",
        ),
        (
            b"https://example.com/path?x=a%2Bb+c",
            "x=a%2Bb+c",
            [["x", "a+b c"]],
            "https://example.com/path?x=a%2Bb+c",
        ),
        (
            "https://example.com/path?x=%C3%A9".encode(),
            "x=%C3%A9",
            [["x", "é"]],
            "https://example.com/path?x=%C3%A9",
        ),
        (
            b"https://example.com/path?x=%2f",
            "x=%2F",
            [["x", "/"]],
            "https://example.com/path?x=%2F",
        ),
        (
            b"https://example.com/path?x",
            "x=",
            [["x", ""]],
            "https://example.com/path?x=",
        ),
        (
            b"https://example.com/path?x=%ZZ",
            "x=%25ZZ",
            [["x", "%ZZ"]],
            "https://example.com/path?x=%25ZZ",
        ),
        (
            b"https://example.com/path#frag",
            "",
            [],
            "https://example.com/path#frag",
        ),
    ],
)
def test_shared_query_canonicalization_matches_node_and_python(
    raw: bytes,
    expected_query: str,
    expected_pairs: list[list[str]],
    expected_url: str,
) -> None:
    run = _harness().evaluate(raw)

    assert run.comparison.classification == "match"
    assert run.signature is None
    assert run.candidate.exit_code == 0
    assert run.oracle.exit_code == 0
    assert _payload(run.candidate.stdout.text) == {
        "ok": True,
        "pairs": expected_pairs,
        "query": expected_query,
        "url": expected_url,
    }


@pytest.mark.parametrize(
    ("raw", "node_query", "python_query"),
    [
        (
            b"https://example.com/path?x=~+*",
            "x=%7E+*",
            "x=~+%2A",
        ),
        (
            b"https://example.com/path?x=!*()~",
            "x=%21*%28%29%7E",
            "x=%21%2A%28%29~",
        ),
    ],
)
def test_native_form_percent_policy_surfaces_query_canonicalization_mismatch(
    raw: bytes,
    node_query: str,
    python_query: str,
) -> None:
    run = _harness().evaluate(raw)

    assert run.comparison.classification == "product_mismatch"
    assert run.comparison.mismatches == ("stdout",)
    assert run.signature is not None
    assert run.signature.kind == "product_mismatch"
    assert run.signature.dimensions == ("stdout",)
    assert _payload(run.candidate.stdout.text)["query"] == node_query
    assert _payload(run.oracle.stdout.text)["query"] == python_query


@pytest.mark.parametrize(
    "raw",
    [
        b"https://example.com/path?x=%FF",
        b"https://example.com/path?x=%E2%82",
    ],
)
def test_invalid_percent_decoded_utf8_surfaces_product_mismatch(raw: bytes) -> None:
    run = _harness().evaluate(raw)

    assert run.comparison.classification == "product_mismatch"
    assert run.comparison.mismatches == ("stdout",)
    assert run.signature is not None
    assert _payload(run.candidate.stdout.text) == {
        "ok": True,
        "pairs": [["x", "�"]],
        "query": "x=%EF%BF%BD",
        "url": "https://example.com/path?x=%EF%BF%BD",
    }
    assert _payload(run.oracle.stdout.text) == {
        "error": "query_decode_error",
        "ok": False,
    }


@pytest.mark.parametrize(
    "raw",
    [
        b"ftp://example.com/path?x=1",
        b"/relative/path?x=1",
    ],
)
def test_out_of_scope_or_invalid_url_rejects_canonically(raw: bytes) -> None:
    run = _harness().evaluate(raw)

    assert run.comparison.classification == "match"
    assert run.signature is None
    assert _payload(run.candidate.stdout.text) == {
        "error": "url_parse_error",
        "ok": False,
    }


@pytest.mark.parametrize("raw", [b"ÿ", b"https://example.com/Ã("])
def test_invalid_raw_utf8_rejects_before_url_or_query_processing(raw: bytes) -> None:
    run = _harness().evaluate(raw)

    assert run.comparison.classification == "match"
    assert run.signature is None
    assert _payload(run.candidate.stdout.text) == {
        "error": "unicode_decode_error",
        "ok": False,
    }


def test_discovery_publishes_and_replays_query_percent_policy_divergence(tmp_path) -> None:
    harness = _harness()
    corpus = (
        b"https://example.com/path?a=two+words",
        b"https://example.com/path?x=~+*",
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
        tmp_path / "url-query-canonicalization-repro",
        input_bytes=failure.case,
        expected_signature=failure.signature,
        metadata={"domain": "url-query-canonicalization"},
    )
    replay = harness.replay_repro(repro.path)

    assert replay.reproduced is True
    assert replay.run.signature == failure.signature
    assert replay.bundle.metadata["domain"] == "url-query-canonicalization"


def _execute_command(target: CommandTarget, case: bytes) -> object:
    return target.execute(
        case,
        timeout_seconds=5.0,
        max_output_bytes=4096,
        max_total_output_bytes=8192,
    )


def test_python_runtime_identity_is_bound_and_verified_before_input() -> None:
    target = URLQueryCanonicalizationTarget()
    implementation, python_version = target.runtime_identity
    command = target.as_command_target()

    assert implementation == sys.implementation.name
    assert python_version == platform.python_version()

    argv = list(command.argv)
    argv[argv.index("--python-version") + 1] = "__drift__"
    result = _execute_command(CommandTarget(tuple(argv)), b"https://example.com/?x=1")

    assert result.exit_code == 3
    assert result.stdout.text == ""
    assert result.stderr.text.strip() == "url_query_runtime_identity_mismatch"


def test_node_runtime_identity_is_bound_and_verified_before_input() -> None:
    target = URLNodeQueryCanonicalizationTarget()
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
        b"https://example.com/?x=1",
    )

    assert result.exit_code == 3
    assert result.stdout.text == ""
    assert result.stderr.text.strip() == "url_query_runtime_identity_mismatch"


def test_runtime_identity_changes_replay_context() -> None:
    command = URLQueryCanonicalizationTarget().as_command_target()
    argv = list(command.argv)
    argv[argv.index("--python-version") + 1] = "__different_python__"
    drifted = CommandTarget(tuple(argv))

    assert DifferentialHarness(
        candidate=command,
        oracle=command,
    ).replay_context_sha256 != DifferentialHarness(
        candidate=drifted,
        oracle=drifted,
    ).replay_context_sha256


def test_node_target_requires_available_runtime() -> None:
    assert shutil.which("node") is not None

    with pytest.raises(ValueError, match="node_executable"):
        URLNodeQueryCanonicalizationTarget(node_executable="")
    with pytest.raises(RuntimeError, match="Node runtime is required"):
        URLNodeQueryCanonicalizationTarget(node_executable="__missing_conformance_node__")
