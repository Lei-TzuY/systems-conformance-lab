from __future__ import annotations

import json

import pytest

from systems_conformance import (
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
