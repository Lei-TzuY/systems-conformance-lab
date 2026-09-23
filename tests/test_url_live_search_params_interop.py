from __future__ import annotations

import json
import platform
import shutil
import sys

import pytest

from systems_conformance import (
    CommandTarget,
    DifferentialHarness,
    URLLiveSearchParamsNodeTarget,
    URLLiveSearchParamsTarget,
    run_failure_discovery_campaign,
)

_APPEND = 1
_SET = 2
_DELETE = 3
_SORT = 4
_SET_SEARCH = 5


def _field(value: str | bytes) -> bytes:
    raw = value if isinstance(value, bytes) else value.encode("utf-8")
    return len(raw).to_bytes(4, "big") + raw


def _request(
    url: str | bytes,
    operations: list[tuple[str, ...]],
) -> bytes:
    raw = bytearray(_field(url))
    raw += len(operations).to_bytes(4, "big")

    for operation in operations:
        op = operation[0]
        if op == "append":
            raw.append(_APPEND)
            raw += _field(operation[1])
            raw += _field(operation[2])
        elif op == "set":
            raw.append(_SET)
            raw += _field(operation[1])
            raw += _field(operation[2])
        elif op == "delete":
            raw.append(_DELETE)
            raw += _field(operation[1])
        elif op == "sort":
            raw.append(_SORT)
        elif op == "set_search":
            raw.append(_SET_SEARCH)
            raw += _field(operation[1])
        else:
            raise AssertionError(f"unsupported test operation: {op}")
    return bytes(raw)


def _harness(
    *,
    max_url_bytes: int = 16 * 1024,
    max_operations: int = 64,
    max_field_bytes: int = 4096,
) -> DifferentialHarness:
    return DifferentialHarness(
        candidate=URLLiveSearchParamsNodeTarget(
            max_url_bytes=max_url_bytes,
            max_operations=max_operations,
            max_field_bytes=max_field_bytes,
        ).as_command_target(),
        oracle=URLLiveSearchParamsTarget(
            max_url_bytes=max_url_bytes,
            max_operations=max_operations,
            max_field_bytes=max_field_bytes,
        ).as_command_target(),
        timeout_seconds=5.0,
        max_input_bytes=128 * 1024,
        max_output_bytes=2 * 1024 * 1024,
        max_total_output_bytes=4 * 1024 * 1024,
    )


def _payload(text: str) -> dict[str, object]:
    return json.loads(text)


def test_node_runtime_is_available_for_live_url_search_params_interop() -> None:
    assert shutil.which("node") is not None


def test_bidirectional_live_coupling_matches_shared_subset() -> None:
    raw = _request(
        "https://example.com/path?a=1&a=2#frag",
        [
            ("append", "b", "two words"),
            ("set", "a", "9"),
            ("set_search", "?z=a%20b&z=2"),
            ("append", "q", "+"),
            ("sort",),
            ("delete", "z"),
        ],
    )

    run = _harness().evaluate(raw)

    assert run.comparison.classification == "match"
    assert run.signature is None
    assert _payload(run.candidate.stdout.text) == {
        "ok": True,
        "states": [
            {
                "href": "https://example.com/path?a=1&a=2#frag",
                "pairs": [["a", "1"], ["a", "2"]],
                "query": "a=1&a=2",
                "search": "?a=1&a=2",
            },
            {
                "href": "https://example.com/path?a=1&a=2&b=two+words#frag",
                "pairs": [["a", "1"], ["a", "2"], ["b", "two words"]],
                "query": "a=1&a=2&b=two+words",
                "search": "?a=1&a=2&b=two+words",
            },
            {
                "href": "https://example.com/path?a=9&b=two+words#frag",
                "pairs": [["a", "9"], ["b", "two words"]],
                "query": "a=9&b=two+words",
                "search": "?a=9&b=two+words",
            },
            {
                "href": "https://example.com/path?z=a%20b&z=2#frag",
                "pairs": [["z", "a b"], ["z", "2"]],
                "query": "z=a+b&z=2",
                "search": "?z=a%20b&z=2",
            },
            {
                "href": "https://example.com/path?z=a+b&z=2&q=%2B#frag",
                "pairs": [["z", "a b"], ["z", "2"], ["q", "+"]],
                "query": "z=a+b&z=2&q=%2B",
                "search": "?z=a+b&z=2&q=%2B",
            },
            {
                "href": "https://example.com/path?q=%2B&z=a+b&z=2#frag",
                "pairs": [["q", "+"], ["z", "a b"], ["z", "2"]],
                "query": "q=%2B&z=a+b&z=2",
                "search": "?q=%2B&z=a+b&z=2",
            },
            {
                "href": "https://example.com/path?q=%2B#frag",
                "pairs": [["q", "+"]],
                "query": "q=%2B",
                "search": "?q=%2B",
            },
        ],
    }


def test_direct_search_replacement_updates_existing_params_view_without_canonicalizing_href() -> None:
    raw = _request(
        "https://example.com/?x=1",
        [("set_search", "?a=two%20words&a=2")],
    )

    run = _harness().evaluate(raw)

    assert run.comparison.classification == "match"
    states = _payload(run.candidate.stdout.text)["states"]
    assert states[1] == {
        "href": "https://example.com/?a=two%20words&a=2",
        "pairs": [["a", "two words"], ["a", "2"]],
        "query": "a=two+words&a=2",
        "search": "?a=two%20words&a=2",
    }


def test_params_mutation_canonicalizes_direct_search_replacement() -> None:
    raw = _request(
        "https://example.com/?x=1",
        [
            ("set_search", "?a=two%20words"),
            ("append", "b", "3"),
        ],
    )

    run = _harness().evaluate(raw)

    assert run.comparison.classification == "match"
    states = _payload(run.candidate.stdout.text)["states"]
    assert states[1]["href"] == "https://example.com/?a=two%20words"
    assert states[1]["query"] == "a=two+words"
    assert states[2]["href"] == "https://example.com/?a=two+words&b=3"
    assert states[2]["search"] == "?a=two+words&b=3"


def test_native_form_encoding_difference_propagates_into_live_url() -> None:
    raw = _request(
        "https://example.com/?x=1",
        [("append", "y", "~*")],
    )

    run = _harness().evaluate(raw)

    assert run.comparison.classification == "product_mismatch"
    assert run.comparison.mismatches == ("stdout",)
    assert run.signature is not None
    assert run.signature.kind == "product_mismatch"
    assert run.signature.dimensions == ("stdout",)

    candidate_states = _payload(run.candidate.stdout.text)["states"]
    oracle_states = _payload(run.oracle.stdout.text)["states"]

    assert candidate_states[-1] == {
        "href": "https://example.com/?x=1&y=%7E*",
        "pairs": [["x", "1"], ["y", "~*"]],
        "query": "x=1&y=%7E*",
        "search": "?x=1&y=%7E*",
    }
    assert oracle_states[-1] == {
        "href": "https://example.com/?x=1&y=~%2A",
        "pairs": [["x", "1"], ["y", "~*"]],
        "query": "x=1&y=~%2A",
        "search": "?x=1&y=~%2A",
    }


def test_live_coupling_divergence_is_discovered_published_and_replayed(tmp_path) -> None:
    harness = _harness()
    corpus = (
        _request("https://example.com/?x=1", [("append", "y", "ok")]),
        _request("https://example.com/?x=1", [("append", "y", "~*")]),
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
        tmp_path / "url-live-search-params-repro",
        input_bytes=failure.case,
        expected_signature=failure.signature,
        metadata={"domain": "url-live-search-params-coupling"},
    )
    replay = harness.replay_repro(repro.path)

    assert replay.reproduced is True
    assert replay.run.signature == failure.signature
    assert replay.bundle.metadata["domain"] == "url-live-search-params-coupling"


@pytest.mark.parametrize(
    "raw",
    [
        b"",
        b"\x00\x00\x00",
        _field("https://example.com/") + (1).to_bytes(4, "big"),
        _request("https://example.com/", []) + b"trailing",
    ],
)
def test_invalid_binary_framing_rejects_canonically(raw: bytes) -> None:
    run = _harness().evaluate(raw)

    assert run.comparison.classification == "match"
    assert run.signature is None
    assert _payload(run.candidate.stdout.text) == {
        "error": "request_error",
        "ok": False,
    }


def test_invalid_utf8_url_field_rejects_before_url_parsing() -> None:
    raw = _field(b"\xff") + (0).to_bytes(4, "big")

    run = _harness().evaluate(raw)

    assert run.comparison.classification == "match"
    assert _payload(run.candidate.stdout.text) == {
        "error": "unicode_decode_error",
        "ok": False,
    }


@pytest.mark.parametrize(
    "url",
    [
        "/relative?x=1",
        "mailto:user@example.com?x=1",
        "ftp://example.com/?x=1",
    ],
)
def test_out_of_scope_urls_reject_before_coupling(url: str) -> None:
    run = _harness().evaluate(_request(url, []))

    assert run.comparison.classification == "match"
    assert _payload(run.candidate.stdout.text) == {
        "error": "url_parse_error",
        "ok": False,
    }


def test_url_byte_budget_fails_closed_in_worker() -> None:
    raw = _request("https://example.com/", [])

    run = _harness(max_url_bytes=4).evaluate(raw)

    assert run.comparison.classification == "match"
    assert _payload(run.candidate.stdout.text) == {
        "error": "request_error",
        "ok": False,
    }


def test_operation_budget_fails_closed_in_worker() -> None:
    raw = _request(
        "https://example.com/",
        [("append", "a", "1"), ("delete", "a")],
    )

    run = _harness(max_operations=1).evaluate(raw)

    assert run.comparison.classification == "match"
    assert _payload(run.candidate.stdout.text) == {
        "error": "request_error",
        "ok": False,
    }


def test_field_budget_fails_closed_in_worker() -> None:
    raw = _request("https://example.com/", [("append", "ab", "x")])

    run = _harness(max_field_bytes=1).evaluate(raw)

    assert run.comparison.classification == "match"
    assert _payload(run.candidate.stdout.text) == {
        "error": "request_error",
        "ok": False,
    }


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("max_url_bytes", 0),
        ("max_url_bytes", True),
        ("max_operations", -1),
        ("max_operations", True),
        ("max_field_bytes", 0),
        ("max_field_bytes", 1.5),
    ],
)
def test_invalid_structural_budget_rejects_before_spawn(
    field: str,
    value: object,
) -> None:
    kwargs = {field: value}
    with pytest.raises(ValueError, match=field):
        URLLiveSearchParamsTarget(**kwargs)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match=field):
        URLLiveSearchParamsNodeTarget(**kwargs)  # type: ignore[arg-type]


def _execute_command(
    target: CommandTarget,
    case: bytes = _request("https://example.com/?x=1", []),
):
    return target.execute(
        case,
        timeout_seconds=5.0,
        max_output_bytes=4096,
        max_total_output_bytes=8192,
    )


def test_python_runtime_identity_is_bound_and_verified_before_input() -> None:
    target = URLLiveSearchParamsTarget()
    implementation, python_version = target.runtime_identity
    command = target.as_command_target()

    assert implementation == sys.implementation.name
    assert python_version == platform.python_version()
    assert implementation in command.argv
    assert python_version in command.argv

    argv = list(command.argv)
    argv[argv.index("--python-version") + 1] = "__drift__"
    result = _execute_command(CommandTarget(tuple(argv)))

    assert result.exit_code == 3
    assert result.stdout.text == ""
    assert result.stderr.text.strip() == "url_live_search_params_runtime_identity_mismatch"


def test_node_runtime_identity_is_bound_and_verified_before_input() -> None:
    target = URLLiveSearchParamsNodeTarget()
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
    assert result.stderr.text.strip() == "url_live_search_params_runtime_identity_mismatch"


def test_structural_configuration_changes_replay_context() -> None:
    baseline = URLLiveSearchParamsTarget(max_operations=8).as_command_target()
    changed = URLLiveSearchParamsTarget(max_operations=9).as_command_target()

    assert baseline.argv != changed.argv
    assert DifferentialHarness(
        candidate=baseline,
        oracle=baseline,
    ).replay_context_sha256 != DifferentialHarness(
        candidate=changed,
        oracle=changed,
    ).replay_context_sha256


def test_node_target_requires_available_runtime() -> None:
    with pytest.raises(ValueError, match="node_executable"):
        URLLiveSearchParamsNodeTarget(node_executable="")
    with pytest.raises(RuntimeError, match="Node runtime is required"):
        URLLiveSearchParamsNodeTarget(
            node_executable="__missing_conformance_node__"
        )
