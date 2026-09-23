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
        max_input_bytes=32 * 1024,
        max_output_bytes=128 * 1024,
        max_total_output_bytes=256 * 1024,
    )


def _payload(text: str) -> dict[str, object]:
    return json.loads(text)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (
            b"https://example.com/?x=a%20b#frag",
            {
                "href": "https://example.com/?x=a+b#frag",
                "ok": True,
                "pairs": [["x", "a b"]],
                "query": "x=a+b",
            },
        ),
        (
            b"https://example.com/path?a=1&a=2&empty=&flag",
            {
                "href": "https://example.com/path?a=1&a=2&empty=&flag=",
                "ok": True,
                "pairs": [
                    ["a", "1"],
                    ["a", "2"],
                    ["empty", ""],
                    ["flag", ""],
                ],
                "query": "a=1&a=2&empty=&flag=",
            },
        ),
        (
            b"https://example.com/?x=%ZZ",
            {
                "href": "https://example.com/?x=%25ZZ",
                "ok": True,
                "pairs": [["x", "%ZZ"]],
                "query": "x=%25ZZ",
            },
        ),
        (
            b"https://example.com/?x=%2f",
            {
                "href": "https://example.com/?x=%2F",
                "ok": True,
                "pairs": [["x", "/"]],
                "query": "x=%2F",
            },
        ),
        (
            "https://example.com/?x=é".encode(),
            {
                "href": "https://example.com/?x=%C3%A9",
                "ok": True,
                "pairs": [["x", "é"]],
                "query": "x=%C3%A9",
            },
        ),
        (
            b"https://example.com/?x=a%2Bb+c",
            {
                "href": "https://example.com/?x=a%2Bb+c",
                "ok": True,
                "pairs": [["x", "a+b c"]],
                "query": "x=a%2Bb+c",
            },
        ),
        (
            b"https://example.com/?",
            {
                "href": "https://example.com/",
                "ok": True,
                "pairs": [],
                "query": "",
            },
        ),
        (
            b"https://example.com/path#frag",
            {
                "href": "https://example.com/path#frag",
                "ok": True,
                "pairs": [],
                "query": "",
            },
        ),
    ],
)
def test_full_url_query_round_trip_matches_shared_subset(
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
        b"https://example.com/?x=\xc3(",
        b"\xe2\x82",
    ],
)
def test_raw_invalid_utf8_rejects_before_url_or_query_processing(raw: bytes) -> None:
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
        b"/relative?x=1",
        b"mailto:user@example.com?x=1",
        b"ftp://example.com/?x=1",
    ],
)
def test_out_of_scope_urls_reject_before_query_canonicalization(raw: bytes) -> None:
    run = _harness().evaluate(raw)

    assert run.comparison.classification == "match"
    assert run.signature is None
    assert _payload(run.candidate.stdout.text) == {
        "error": "url_parse_error",
        "ok": False,
    }


def test_native_query_percent_encoding_policy_surfaces_product_mismatch() -> None:
    run = _harness().evaluate(b"https://example.com/?x=~*")

    assert run.comparison.classification == "product_mismatch"
    assert run.comparison.mismatches == ("stdout",)
    assert run.signature is not None
    assert run.signature.kind == "product_mismatch"
    assert run.signature.dimensions == ("stdout",)
    assert _payload(run.candidate.stdout.text) == {
        "href": "https://example.com/?x=%7E*",
        "ok": True,
        "pairs": [["x", "~*"]],
        "query": "x=%7E*",
    }
    assert _payload(run.oracle.stdout.text) == {
        "href": "https://example.com/?x=~%2A",
        "ok": True,
        "pairs": [["x", "~*"]],
        "query": "x=~%2A",
    }


def test_additional_native_percent_encode_set_divergence_is_stable() -> None:
    run = _harness().evaluate(b"https://example.com/?x=!*()~")

    assert run.comparison.classification == "product_mismatch"
    assert run.comparison.mismatches == ("stdout",)
    assert run.signature is not None
    assert run.signature.dimensions == ("stdout",)
    assert _payload(run.candidate.stdout.text)["query"] == "x=%21*%28%29%7E"
    assert _payload(run.oracle.stdout.text)["query"] == "x=%21%2A%28%29~"


@pytest.mark.parametrize(
    "raw",
    [
        b"https://example.com/?x=%FF",
        b"https://example.com/?x=%E2%82",
    ],
)
def test_invalid_percent_decoded_utf8_surfaces_product_mismatch(raw: bytes) -> None:
    run = _harness().evaluate(raw)

    assert run.comparison.classification == "product_mismatch"
    assert run.comparison.mismatches == ("stdout",)
    assert run.signature is not None
    assert run.signature.kind == "product_mismatch"
    assert run.signature.dimensions == ("stdout",)
    assert _payload(run.candidate.stdout.text) == {
        "href": "https://example.com/?x=%EF%BF%BD",
        "ok": True,
        "pairs": [["x", "�"]],
        "query": "x=%EF%BF%BD",
    }
    assert _payload(run.oracle.stdout.text) == {
        "error": "form_decode_error",
        "ok": False,
    }


def test_percent_encoding_discovery_publishes_and_replays_witness(tmp_path) -> None:
    harness = _harness()
    corpus = (
        b"https://example.com/?x=a%20b",
        b"https://example.com/?x=~*",
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
        tmp_path / "url-query-percent-repro",
        input_bytes=failure.case,
        expected_signature=failure.signature,
        metadata={"domain": "url-query-percent-canonicalization"},
    )
    replay = harness.replay_repro(repro.path)

    assert replay.reproduced is True
    assert replay.run.signature == failure.signature
    assert replay.bundle.metadata["domain"] == "url-query-percent-canonicalization"


def test_invalid_percent_utf8_discovery_publishes_and_replays_witness(tmp_path) -> None:
    harness = _harness()
    corpus = (
        b"https://example.com/?x=%C3%A9",
        b"https://example.com/?x=%FF",
    )

    discovery = run_failure_discovery_campaign(
        cases=corpus.__getitem__,
        evaluate=harness.compare,
        max_evaluations=len(corpus),
        max_unique_failures=4,
    )

    assert discovery.evaluations == len(corpus)
    assert discovery.exhausted_budget is True
    assert len(discovery.failures) == 1
    failure = discovery.failures[0]
    assert failure.evaluation_index == 1
    assert failure.case == corpus[1]
    assert failure.signature.kind == "product_mismatch"
    assert failure.signature.dimensions == ("stdout",)

    repro = harness.write_repro(
        tmp_path / "url-query-percent-utf8-repro",
        input_bytes=failure.case,
        expected_signature=failure.signature,
        metadata={"domain": "url-query-percent-decoded-utf8"},
    )
    replay = harness.replay_repro(repro.path)

    assert replay.reproduced is True
    assert replay.run.signature == failure.signature
    assert replay.bundle.metadata["domain"] == "url-query-percent-decoded-utf8"


def _execute_command(target: CommandTarget, case: bytes = b"https://example.com/?x=1"):
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
    assert command.argv[-4:] == (
        "--python-implementation",
        implementation,
        "--python-version",
        python_version,
    )

    argv = list(command.argv)
    argv[argv.index("--python-version") + 1] = "__drift__"
    result = _execute_command(CommandTarget(tuple(argv)))

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
        CommandTarget((target.node_executable, "-e", drifted_script))
    )

    assert result.exit_code == 3
    assert result.stdout.text == ""
    assert result.stderr.text.strip() == "url_query_runtime_identity_mismatch"


def test_runtime_identity_changes_query_canonicalization_replay_context() -> None:
    command = URLQueryCanonicalizationTarget().as_command_target()
    argv = list(command.argv)
    argv[argv.index("--python-version") + 1] = "__different_python__"
    drifted = CommandTarget(tuple(argv))

    baseline = DifferentialHarness(candidate=command, oracle=command)
    changed = DifferentialHarness(candidate=drifted, oracle=drifted)

    assert baseline.replay_context_sha256 != changed.replay_context_sha256


def test_node_target_requires_available_runtime() -> None:
    assert shutil.which("node") is not None

    with pytest.raises(ValueError, match="node_executable"):
        URLNodeQueryCanonicalizationTarget(node_executable="")
    with pytest.raises(RuntimeError, match="Node runtime is required"):
        URLNodeQueryCanonicalizationTarget(
            node_executable="__missing_conformance_node__"
        )
