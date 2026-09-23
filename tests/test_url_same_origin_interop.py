from __future__ import annotations

import json
import platform
import shutil
import sys
import unicodedata

import pytest

from systems_conformance import (
    CommandTarget,
    DifferentialHarness,
    URLNodeSameOriginTarget,
    URLSameOriginTarget,
    run_failure_discovery_campaign,
)


def _request(left: str | bytes, right: str | bytes) -> bytes:
    left_raw = left if isinstance(left, bytes) else left.encode("utf-8")
    right_raw = right if isinstance(right, bytes) else right.encode("utf-8")
    return len(left_raw).to_bytes(4, "big") + left_raw + right_raw


def _harness(*, max_url_bytes: int = 16 * 1024) -> DifferentialHarness:
    return DifferentialHarness(
        candidate=URLNodeSameOriginTarget(
            max_url_bytes=max_url_bytes,
        ).as_command_target(),
        oracle=URLSameOriginTarget(
            max_url_bytes=max_url_bytes,
        ).as_command_target(),
        timeout_seconds=5.0,
        max_input_bytes=64 * 1024,
        max_output_bytes=64 * 1024,
        max_total_output_bytes=128 * 1024,
    )


def _payload(text: str) -> dict[str, object]:
    return json.loads(text)


@pytest.mark.parametrize(
    ("left", "right", "left_origin", "right_origin", "same_origin"),
    [
        (
            "https://EXAMPLE.com:443/a?x=1",
            "https://example.com/b#frag",
            "https://example.com",
            "https://example.com",
            True,
        ),
        (
            "http://example.com:80/a",
            "http://example.com/",
            "http://example.com",
            "http://example.com",
            True,
        ),
        (
            "https://bücher.example/a",
            "https://xn--bcher-kva.example:443/b",
            "https://xn--bcher-kva.example",
            "https://xn--bcher-kva.example",
            True,
        ),
        (
            "https://user:pass@example.com/a",
            "https://example.com/other?x=1#frag",
            "https://example.com",
            "https://example.com",
            True,
        ),
        (
            "http://example.com/",
            "https://example.com/",
            "http://example.com",
            "https://example.com",
            False,
        ),
        (
            "https://example.com:8443/",
            "https://example.com/",
            "https://example.com:8443",
            "https://example.com",
            False,
        ),
    ],
)
def test_http_origin_shared_subset_matches(
    left: str,
    right: str,
    left_origin: str,
    right_origin: str,
    same_origin: bool,
) -> None:
    run = _harness().evaluate(_request(left, right))

    assert run.comparison.classification == "match"
    assert run.signature is None
    assert run.candidate.exit_code == 0
    assert run.oracle.exit_code == 0
    assert _payload(run.candidate.stdout.text) == {
        "left_origin": left_origin,
        "ok": True,
        "right_origin": right_origin,
        "same_origin": same_origin,
    }


@pytest.mark.parametrize(
    "raw",
    [
        _request(b"\xff", "https://example.com/"),
        _request("https://example.com/", b"\xe2\x82"),
    ],
)
def test_invalid_utf8_rejects_before_origin_processing(raw: bytes) -> None:
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
        b"\x00\x00\x00",
        (10).to_bytes(4, "big") + b"short",
    ],
)
def test_invalid_request_framing_rejects_canonically(raw: bytes) -> None:
    run = _harness().evaluate(raw)

    assert run.comparison.classification == "match"
    assert run.signature is None
    assert _payload(run.candidate.stdout.text) == {
        "error": "request_error",
        "ok": False,
    }


@pytest.mark.parametrize(
    ("left", "right"),
    [
        ("/relative", "https://example.com/"),
        ("ftp://example.com/", "https://example.com/"),
        ("https://", "https://example.com/"),
        ("https://[::1]/", "https://[::1]/"),
    ],
)
def test_out_of_scope_origin_inputs_reject_canonically(
    left: str,
    right: str,
) -> None:
    run = _harness().evaluate(_request(left, right))

    assert run.comparison.classification == "match"
    assert run.signature is None
    assert _payload(run.candidate.stdout.text) == {
        "error": "url_origin_error",
        "ok": False,
    }


def test_per_url_byte_budget_fails_closed() -> None:
    raw = _request("https://example.com/", "https://example.com/")

    run = _harness(max_url_bytes=8).evaluate(raw)

    assert run.comparison.classification == "match"
    assert run.signature is None
    assert _payload(run.candidate.stdout.text) == {
        "error": "request_error",
        "ok": False,
    }


def test_idna_policy_difference_changes_same_origin_security_decision() -> None:
    raw = _request("https://faß.de/", "https://fass.de/")

    run = _harness().evaluate(raw)

    assert run.comparison.classification == "product_mismatch"
    assert run.comparison.mismatches == ("stdout",)
    assert run.signature is not None
    assert run.signature.kind == "product_mismatch"
    assert run.signature.dimensions == ("stdout",)
    assert _payload(run.candidate.stdout.text) == {
        "left_origin": "https://xn--fa-hia.de",
        "ok": True,
        "right_origin": "https://fass.de",
        "same_origin": False,
    }
    assert _payload(run.oracle.stdout.text) == {
        "left_origin": "https://fass.de",
        "ok": True,
        "right_origin": "https://fass.de",
        "same_origin": True,
    }


def test_same_origin_divergence_is_discovered_published_and_replayed(tmp_path) -> None:
    harness = _harness()
    corpus = (
        _request(
            "https://bücher.example/",
            "https://xn--bcher-kva.example/",
        ),
        _request("https://faß.de/", "https://fass.de/"),
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
        tmp_path / "same-origin-repro",
        input_bytes=failure.case,
        expected_signature=failure.signature,
        metadata={"domain": "http-same-origin-idna-policy"},
    )
    replay = harness.replay_repro(repro.path)

    assert replay.reproduced is True
    assert replay.run.signature == failure.signature
    assert replay.bundle.metadata["domain"] == "http-same-origin-idna-policy"


@pytest.mark.parametrize("max_url_bytes", [0, -1, True, 1.5])
def test_invalid_url_byte_budget_rejects_before_spawn(max_url_bytes: object) -> None:
    with pytest.raises(ValueError, match="max_url_bytes"):
        URLSameOriginTarget(max_url_bytes=max_url_bytes)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="max_url_bytes"):
        URLNodeSameOriginTarget(max_url_bytes=max_url_bytes)  # type: ignore[arg-type]


def _execute_command(
    target: CommandTarget,
    case: bytes = _request("https://example.com/", "https://example.com/"),
):
    return target.execute(
        case,
        timeout_seconds=5.0,
        max_output_bytes=4096,
        max_total_output_bytes=8192,
    )


def test_python_runtime_identity_binds_idna_unicode_table() -> None:
    target = URLSameOriginTarget()
    implementation, python_version, idna_unicode_version = target.runtime_identity
    command = target.as_command_target()

    assert implementation == sys.implementation.name
    assert python_version == platform.python_version()
    assert idna_unicode_version == unicodedata.ucd_3_2_0.unidata_version
    assert implementation in command.argv
    assert python_version in command.argv
    assert idna_unicode_version in command.argv

    argv = list(command.argv)
    argv[argv.index("--idna-unicode-version") + 1] = "__drift__"
    result = _execute_command(CommandTarget(tuple(argv)))

    assert result.exit_code == 3
    assert result.stdout.text == ""
    assert result.stderr.text.strip() == "url_same_origin_runtime_identity_mismatch"


def test_node_runtime_identity_binds_icu_and_unicode_tables() -> None:
    target = URLNodeSameOriginTarget()
    node_version, icu_version, unicode_version = target.runtime_identity
    command = target.as_command_target()

    assert node_version.startswith("v")
    assert icu_version
    assert unicode_version
    assert f"const EXPECTED_NODE_VERSION = {json.dumps(node_version)};" in command.argv[2]
    assert f"const EXPECTED_ICU_VERSION = {json.dumps(icu_version)};" in command.argv[2]
    assert (
        f"const EXPECTED_UNICODE_VERSION = {json.dumps(unicode_version)};"
        in command.argv[2]
    )

    expected = f"const EXPECTED_UNICODE_VERSION = {json.dumps(unicode_version)};"
    drifted_script = command.argv[2].replace(
        expected,
        'const EXPECTED_UNICODE_VERSION = "__drift__";',
        1,
    )
    result = _execute_command(
        CommandTarget((target.node_executable, "-e", drifted_script))
    )

    assert result.exit_code == 3
    assert result.stdout.text == ""
    assert result.stderr.text.strip() == "url_same_origin_runtime_identity_mismatch"


def test_url_budget_changes_replay_context() -> None:
    baseline = URLSameOriginTarget(max_url_bytes=1024).as_command_target()
    changed = URLSameOriginTarget(max_url_bytes=2048).as_command_target()

    assert baseline.argv != changed.argv
    assert DifferentialHarness(
        candidate=baseline,
        oracle=baseline,
    ).replay_context_sha256 != DifferentialHarness(
        candidate=changed,
        oracle=changed,
    ).replay_context_sha256


def test_node_target_requires_available_runtime() -> None:
    assert shutil.which("node") is not None

    with pytest.raises(ValueError, match="node_executable"):
        URLNodeSameOriginTarget(node_executable="")
    with pytest.raises(RuntimeError, match="Node runtime is required"):
        URLNodeSameOriginTarget(node_executable="__missing_conformance_node__")
