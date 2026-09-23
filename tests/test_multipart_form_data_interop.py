from __future__ import annotations

import json
import platform
import shutil
import sys

import pytest

from systems_conformance import (
    CommandTarget,
    DifferentialHarness,
    MultipartFormDataNodeTarget,
    MultipartFormDataTarget,
    run_failure_discovery_campaign,
)
from systems_conformance.multipart_form_data_adapter import (
    MAX_CONFIGURED_MULTIPART_BODY_BYTES,
    MULTIPART_FORM_DATA_BOUNDARY,
)

_BOUNDARY = MULTIPART_FORM_DATA_BOUNDARY.encode("ascii")


def _part(
    *,
    headers: tuple[bytes, ...],
    body: bytes,
    line_ending: bytes = b"\r\n",
) -> bytes:
    return (
        b"--"
        + _BOUNDARY
        + line_ending
        + line_ending.join(headers)
        + line_ending
        + line_ending
        + body
        + line_ending
    )


def _multipart(
    *parts: bytes,
    line_ending: bytes = b"\r\n",
    close: bool = True,
) -> bytes:
    result = b"".join(parts)
    if close:
        result += b"--" + _BOUNDARY + b"--" + line_ending
    return result


def _text_part(
    name: str,
    body: bytes,
    *,
    content_type: str | None = None,
    line_ending: bytes = b"\r\n",
) -> bytes:
    headers = [f'Content-Disposition: form-data; name="{name}"'.encode("ascii")]
    if content_type is not None:
        headers.append(f"Content-Type: {content_type}".encode("ascii"))
    return _part(headers=tuple(headers), body=body, line_ending=line_ending)


def _file_part(
    name: str,
    filename: str,
    body: bytes,
    *,
    content_type: str = "application/octet-stream",
    line_ending: bytes = b"\r\n",
) -> bytes:
    return _part(
        headers=(
            (
                f'Content-Disposition: form-data; name="{name}"; '
                f'filename="{filename}"'
            ).encode("ascii"),
            f"Content-Type: {content_type}".encode("ascii"),
        ),
        body=body,
        line_ending=line_ending,
    )


def _harness(*, max_body_bytes: int = 64 * 1024) -> DifferentialHarness:
    return DifferentialHarness(
        candidate=MultipartFormDataNodeTarget(
            max_body_bytes=max_body_bytes
        ).as_command_target(),
        oracle=MultipartFormDataTarget(
            max_body_bytes=max_body_bytes
        ).as_command_target(),
        timeout_seconds=5.0,
        max_input_bytes=512 * 1024,
        max_output_bytes=2 * 1024 * 1024,
        max_total_output_bytes=4 * 1024 * 1024,
    )


def _payload(text: str) -> dict[str, object]:
    return json.loads(text)


def _text_entry(name: str, value: str) -> dict[str, object]:
    return {
        "kind": "text",
        "name_utf8_hex": name.encode("utf-8").hex(),
        "value_utf8_hex": value.encode("utf-8").hex(),
    }


def _file_entry(
    name: str,
    filename: str,
    content_type: str,
    body: bytes,
) -> dict[str, object]:
    return {
        "body_hex": body.hex(),
        "content_type": content_type,
        "filename_utf8_hex": filename.encode("utf-8").hex(),
        "kind": "file",
        "name_utf8_hex": name.encode("utf-8").hex(),
    }


@pytest.mark.parametrize(
    ("case", "entries"),
    [
        (
            _multipart(_text_part("x", b"hello")),
            [_text_entry("x", "hello")],
        ),
        (
            _multipart(
                _text_part("x", b"first"),
                _text_part("x", b"second"),
                _text_part("empty", b""),
            ),
            [
                _text_entry("x", "first"),
                _text_entry("x", "second"),
                _text_entry("empty", ""),
            ],
        ),
        (
            _multipart(
                _text_part(
                    "snow",
                    "\N{SNOWMAN}".encode("utf-8"),
                    content_type="text/plain; charset=utf-8",
                )
            ),
            [_text_entry("snow", "\N{SNOWMAN}")],
        ),
        (
            _multipart(
                _file_part(
                    "upload",
                    "a.bin",
                    b"ABC\x00DEF\xff",
                    content_type="application/octet-stream",
                )
            ),
            [
                _file_entry(
                    "upload",
                    "a.bin",
                    "application/octet-stream",
                    b"ABC\x00DEF\xff",
                )
            ],
        ),
    ],
)
def test_shared_multipart_subset_matches(
    case: bytes,
    entries: list[dict[str, object]],
) -> None:
    run = _harness().evaluate(case)

    assert run.comparison.classification == "match"
    assert run.signature is None
    assert _payload(run.candidate.stdout.text) == {
        "entries": entries,
        "ok": True,
    }


@pytest.mark.parametrize("case", [b"", b"not a multipart body"])
def test_shared_invalid_multipart_returns_canonical_error(case: bytes) -> None:
    run = _harness().evaluate(case)

    assert run.comparison.classification == "match"
    assert run.signature is None
    assert _payload(run.candidate.stdout.text) == {
        "error": "multipart_parse_error",
        "ok": False,
    }


def test_exact_body_budget_succeeds() -> None:
    case = _multipart(_text_part("x", b"hello"))
    run = _harness(max_body_bytes=len(case)).evaluate(case)

    assert run.comparison.classification == "match"
    assert run.signature is None
    assert _payload(run.candidate.stdout.text)["ok"] is True


def test_over_body_budget_fails_closed_before_native_parsing() -> None:
    case = _multipart(_text_part("x", b"hello"))
    run = _harness(max_body_bytes=len(case) - 1).evaluate(case)

    assert run.comparison.classification == "match"
    assert run.signature is None
    assert _payload(run.candidate.stdout.text) == {
        "error": "input_too_large",
        "ok": False,
    }


def test_charset_policy_surfaces_native_text_decoding_difference() -> None:
    case = _multipart(
        _text_part(
            "x",
            b"\xe9",
            content_type="text/plain; charset=iso-8859-1",
        )
    )
    run = _harness().evaluate(case)

    assert run.comparison.classification == "product_mismatch"
    assert run.comparison.mismatches == ("stdout",)
    assert run.signature is not None
    assert run.signature.kind == "product_mismatch"
    assert _payload(run.oracle.stdout.text) == {
        "entries": [_text_entry("x", "\N{LATIN SMALL LETTER E WITH ACUTE}")],
        "ok": True,
    }
    assert _payload(run.candidate.stdout.text) == {
        "entries": [
            {
                "kind": "text",
                "name_utf8_hex": b"x".hex(),
                "value_utf8_hex": "\N{REPLACEMENT CHARACTER}".encode("utf-8").hex(),
            }
        ],
        "ok": True,
    }


def test_lf_only_framing_surfaces_native_parser_policy_difference() -> None:
    case = _multipart(
        _text_part("x", b"hello", line_ending=b"\n"),
        line_ending=b"\n",
    )
    run = _harness().evaluate(case)

    assert run.comparison.classification == "product_mismatch"
    assert run.comparison.mismatches == ("stdout",)
    assert _payload(run.oracle.stdout.text) == {
        "entries": [_text_entry("x", "hello")],
        "ok": True,
    }
    assert _payload(run.candidate.stdout.text) == {
        "error": "multipart_parse_error",
        "ok": False,
    }


def test_filename_star_surfaces_native_content_disposition_policy_difference() -> None:
    case = _multipart(
        _part(
            headers=(
                (
                    "Content-Disposition: form-data; name=\"f\"; "
                    "filename*=UTF-8''%E2%98%83.txt"
                ).encode("ascii"),
                b"Content-Type: text/plain",
            ),
            body=b"abc",
        )
    )
    run = _harness().evaluate(case)

    assert run.comparison.classification == "product_mismatch"
    assert run.comparison.mismatches == ("stdout",)
    assert _payload(run.oracle.stdout.text) == {
        "entries": [
            _file_entry(
                "f",
                "\N{SNOWMAN}.txt",
                "text/plain",
                b"abc",
            )
        ],
        "ok": True,
    }
    assert _payload(run.candidate.stdout.text) == {
        "error": "multipart_parse_error",
        "ok": False,
    }


def test_discovery_publishes_and_replays_charset_policy_difference(tmp_path) -> None:
    harness = _harness()
    corpus = (
        _multipart(
            _text_part(
                "x",
                "\N{SNOWMAN}".encode("utf-8"),
                content_type="text/plain; charset=utf-8",
            )
        ),
        _multipart(
            _text_part(
                "x",
                b"\xe9",
                content_type="text/plain; charset=iso-8859-1",
            )
        ),
    )

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
    assert failure.case == corpus[1]
    assert failure.signature.kind == "product_mismatch"
    assert failure.signature.dimensions == ("stdout",)

    repro = harness.write_repro(
        tmp_path / "multipart-form-data-repro",
        input_bytes=failure.case,
        expected_signature=failure.signature,
        metadata={"domain": "multipart-form-data"},
    )
    replay = harness.replay_repro(repro.path)

    assert replay.reproduced is True
    assert replay.run.signature == failure.signature
    assert replay.bundle.metadata["domain"] == "multipart-form-data"


@pytest.mark.parametrize(
    "value",
    [
        True,
        False,
        -1,
        MAX_CONFIGURED_MULTIPART_BODY_BYTES + 1,
        1.5,
        "8",
        None,
    ],
)
def test_targets_reject_invalid_body_budgets(value: object) -> None:
    expected = TypeError if isinstance(value, (bool, float, str)) or value is None else ValueError

    with pytest.raises(expected):
        MultipartFormDataTarget(max_body_bytes=value)  # type: ignore[arg-type]
    with pytest.raises(expected):
        MultipartFormDataNodeTarget(max_body_bytes=value)  # type: ignore[arg-type]


def _execute_command(target: CommandTarget, case: bytes):
    return target.execute(
        case,
        timeout_seconds=5.0,
        max_output_bytes=4096,
        max_total_output_bytes=8192,
    )


def test_python_runtime_identity_is_bound_and_verified_before_input() -> None:
    target = MultipartFormDataTarget()
    implementation, python_version = target.runtime_identity
    command = target.as_command_target()

    assert implementation == sys.implementation.name
    assert python_version == platform.python_version()

    argv = list(command.argv)
    argv[argv.index("--python-version") + 1] = "__drift__"
    result = _execute_command(CommandTarget(tuple(argv)), b"")

    assert result.exit_code == 3
    assert result.stdout.text == ""
    assert (
        result.stderr.text.strip()
        == "multipart_form_data_runtime_identity_mismatch"
    )


def test_node_runtime_identity_is_bound_and_verified_before_input() -> None:
    target = MultipartFormDataNodeTarget()
    node_version, undici_version = target.runtime_identity
    command = target.as_command_target()
    expected_undici = (
        f"const EXPECTED_UNDICI_VERSION = {json.dumps(undici_version)};"
    )

    assert node_version.startswith("v")
    assert expected_undici in command.argv[2]

    drifted_script = command.argv[2].replace(
        expected_undici,
        'const EXPECTED_UNDICI_VERSION = "__drift__";',
        1,
    )
    result = _execute_command(
        CommandTarget((target.node_executable, "-e", drifted_script)),
        b"",
    )

    assert result.exit_code == 3
    assert result.stdout.text == ""
    assert (
        result.stderr.text.strip()
        == "multipart_form_data_runtime_identity_mismatch"
    )


def test_budget_and_runtime_identity_change_replay_context() -> None:
    baseline = MultipartFormDataTarget(max_body_bytes=64).as_command_target()
    smaller = MultipartFormDataTarget(max_body_bytes=32).as_command_target()
    argv = list(baseline.argv)
    argv[argv.index("--python-version") + 1] = "__different_python__"
    drifted = CommandTarget(tuple(argv))

    baseline_context = DifferentialHarness(
        candidate=baseline,
        oracle=baseline,
    ).replay_context_sha256

    for changed in (smaller, drifted):
        assert baseline_context != DifferentialHarness(
            candidate=changed,
            oracle=changed,
        ).replay_context_sha256


def test_node_target_requires_available_runtime() -> None:
    assert shutil.which("node") is not None

    with pytest.raises(ValueError, match="node_executable"):
        MultipartFormDataNodeTarget(node_executable="")
    with pytest.raises(RuntimeError, match="Node runtime is required"):
        MultipartFormDataNodeTarget(
            node_executable="__missing_conformance_node__"
        )
