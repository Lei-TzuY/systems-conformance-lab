from __future__ import annotations

import json
import platform
import sys
import unicodedata

import pytest

from systems_conformance import (
    CommandTarget,
    DeterministicByteMutations,
    DifferentialHarness,
    UnicodeNodeNormalizationTarget,
    UnicodeNormalizationTarget,
    run_fuzz_campaign,
)


def _harness(*, form: str) -> DifferentialHarness:
    return DifferentialHarness(
        candidate=UnicodeNodeNormalizationTarget(form=form).as_command_target(),  # type: ignore[arg-type]
        oracle=UnicodeNormalizationTarget(form=form).as_command_target(),  # type: ignore[arg-type]
        timeout_seconds=5.0,
        max_input_bytes=64 * 1024,
        max_output_bytes=512 * 1024,
        max_total_output_bytes=1024 * 1024,
    )


def _payload(text: str) -> dict[str, object]:
    return json.loads(text)


@pytest.mark.parametrize(
    ("form", "source", "expected"),
    [
        ("NFC", "e\u0301", "é"),
        ("NFD", "é", "e\u0301"),
        ("NFKC", "① ﬁ", "1 fi"),
        ("NFKD", "① ﬁ", "1 fi"),
        ("NFC", "\u1100\u1161", "가"),
        ("NFD", "가", "\u1100\u1161"),
    ],
)
def test_node_matches_python_for_stable_normalization_vectors(
    form: str,
    source: str,
    expected: str,
) -> None:
    run = _harness(form=form).evaluate(source.encode("utf-8"))

    assert run.comparison.classification == "match"
    assert run.signature is None
    assert run.candidate.exit_code == 0
    assert run.oracle.exit_code == 0
    assert _payload(run.candidate.stdout.text) == {
        "ok": True,
        "text": expected,
    }


@pytest.mark.parametrize("form", ["NFC", "NFD", "NFKC", "NFKD"])
def test_normalization_preserves_leading_bom(form: str) -> None:
    raw = b"\xef\xbb\xbf" + "e\u0301".encode("utf-8")
    run = _harness(form=form).evaluate(raw)

    assert run.comparison.classification == "match"
    assert run.signature is None
    payload = _payload(run.candidate.stdout.text)
    assert payload["ok"] is True
    assert str(payload["text"]).startswith("\ufeff")


@pytest.mark.parametrize(
    "raw",
    [
        b"\xff",
        b"A\xc3(",
        b"\xe2\x82",
        b"\xf0\x9f\x99",
    ],
)
@pytest.mark.parametrize("form", ["NFC", "NFD", "NFKC", "NFKD"])
def test_invalid_utf8_rejects_before_normalization(raw: bytes, form: str) -> None:
    run = _harness(form=form).evaluate(raw)

    assert run.comparison.classification == "match"
    assert run.signature is None
    assert _payload(run.candidate.stdout.text) == {
        "error": "unicode_decode_error",
        "ok": False,
    }


def test_cross_runtime_normalization_fuzz_schedule_has_no_differential_failure() -> None:
    cases = DeterministicByteMutations(
        (
            b"ASCII",
            "e\u0301".encode("utf-8"),
            "①".encode(),
            "\u1100\u1161".encode("utf-8"),
        )
    )
    harness = _harness(form="NFKC")

    campaign = run_fuzz_campaign(
        cases=cases,
        evaluate=harness.compare,
        max_evaluations=len(cases),
    )

    assert campaign.classification == "match"
    assert campaign.failing_case is None
    assert campaign.comparison is None
    assert campaign.evaluations == len(cases)
    assert campaign.exhausted_budget is True


@pytest.mark.parametrize("form", ["nfc", "nfkc", "", "NFKC_CASEFOLD", "NONE"])
def test_python_target_rejects_unknown_normalization_form(form: str) -> None:
    with pytest.raises(ValueError, match="form"):
        UnicodeNormalizationTarget(form=form)  # type: ignore[arg-type]


@pytest.mark.parametrize("form", ["nfc", "nfkc", "", "NFKC_CASEFOLD", "NONE"])
def test_node_target_rejects_unknown_normalization_form(form: str) -> None:
    with pytest.raises(ValueError, match="form"):
        UnicodeNodeNormalizationTarget(form=form)  # type: ignore[arg-type]


def test_node_target_rejects_empty_runtime_name() -> None:
    with pytest.raises(ValueError, match="node_executable"):
        UnicodeNodeNormalizationTarget(node_executable="")


def test_node_target_rejects_missing_runtime() -> None:
    with pytest.raises(RuntimeError, match="Node runtime is required"):
        UnicodeNodeNormalizationTarget(node_executable="__missing_conformance_node__")



def _execute_command(target: CommandTarget, case: bytes = b"A"):
    return target.execute(
        case,
        timeout_seconds=5.0,
        max_output_bytes=4096,
        max_total_output_bytes=8192,
    )


def test_python_runtime_identity_is_bound_into_target_argv() -> None:
    target = UnicodeNormalizationTarget()
    command = target.as_command_target()
    implementation, python_version, unicode_version = target.runtime_identity

    assert implementation == sys.implementation.name
    assert python_version == platform.python_version()
    assert unicode_version == unicodedata.unidata_version
    assert command.argv[-6:] == (
        "--python-implementation",
        implementation,
        "--python-version",
        python_version,
        "--unicode-version",
        unicode_version,
    )


def test_python_worker_rejects_runtime_identity_drift_before_input() -> None:
    command = UnicodeNormalizationTarget().as_command_target()
    argv = list(command.argv)
    argv[argv.index("--unicode-version") + 1] = "__drift__"

    result = _execute_command(CommandTarget(tuple(argv)))

    assert result.exit_code == 3
    assert result.timed_out is False
    assert result.stdout.text == ""
    assert result.stderr.text.strip() == "unicode_normalization_runtime_identity_mismatch"


def test_python_runtime_identity_changes_replay_context() -> None:
    command = UnicodeNormalizationTarget().as_command_target()
    argv = list(command.argv)
    argv[argv.index("--python-version") + 1] = "__different_python__"
    drifted = CommandTarget(tuple(argv))

    baseline = DifferentialHarness(candidate=command, oracle=command)
    changed = DifferentialHarness(candidate=drifted, oracle=drifted)

    assert baseline.replay_context_sha256 != changed.replay_context_sha256


def test_node_runtime_identity_is_bound_into_target_script() -> None:
    target = UnicodeNodeNormalizationTarget()
    command = target.as_command_target()
    node_version, icu_version, unicode_version = target.runtime_identity
    script = command.argv[2]

    assert f"const EXPECTED_NODE_VERSION = {json.dumps(node_version)};" in script
    assert f"const EXPECTED_ICU_VERSION = {json.dumps(icu_version)};" in script
    assert f"const EXPECTED_UNICODE_VERSION = {json.dumps(unicode_version)};" in script


def test_node_worker_rejects_runtime_identity_drift_before_input() -> None:
    target = UnicodeNodeNormalizationTarget()
    command = target.as_command_target()
    _node_version, _icu_version, unicode_version = target.runtime_identity
    expected = f"const EXPECTED_UNICODE_VERSION = {json.dumps(unicode_version)};"
    drifted_script = command.argv[2].replace(
        expected,
        'const EXPECTED_UNICODE_VERSION = "__drift__";',
        1,
    )
    assert drifted_script != command.argv[2]

    result = _execute_command(CommandTarget((target.node_executable, "-e", drifted_script)))

    assert result.exit_code == 3
    assert result.timed_out is False
    assert result.stdout.text == ""
    assert result.stderr.text.strip() == "unicode_normalization_runtime_identity_mismatch"


def test_node_runtime_identity_changes_replay_context() -> None:
    target = UnicodeNodeNormalizationTarget()
    command = target.as_command_target()
    node_version, _icu_version, _unicode_version = target.runtime_identity
    expected = f"const EXPECTED_NODE_VERSION = {json.dumps(node_version)};"
    drifted_script = command.argv[2].replace(
        expected,
        'const EXPECTED_NODE_VERSION = "__different_node__";',
        1,
    )
    drifted = CommandTarget((target.node_executable, "-e", drifted_script))

    baseline = DifferentialHarness(candidate=command, oracle=command)
    changed = DifferentialHarness(candidate=drifted, oracle=drifted)

    assert baseline.replay_context_sha256 != changed.replay_context_sha256


def test_node_target_rejects_non_node_executable_during_identity_probe() -> None:
    with pytest.raises(RuntimeError, match="probe Node Unicode runtime identity"):
        UnicodeNodeNormalizationTarget(node_executable=sys.executable)
