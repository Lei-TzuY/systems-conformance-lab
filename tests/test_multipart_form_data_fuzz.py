from __future__ import annotations

import pytest

from systems_conformance import (
    DifferentialHarness,
    MultipartFormDataNodeTarget,
    MultipartFormDataTarget,
    run_failure_discovery_campaign,
)
from systems_conformance.multipart_form_data_adapter import MULTIPART_FORM_DATA_BOUNDARY
from systems_conformance.multipart_form_data_fuzz import multipart_form_data_charset_mutations

_BOUNDARY = MULTIPART_FORM_DATA_BOUNDARY.encode("ascii")


def _text_part(body: bytes, *, charset: bytes = b"utf-8") -> bytes:
    return (
        b"--"
        + _BOUNDARY
        + b"\r\nContent-Disposition: form-data; name=\"x\""
        + b"\r\nContent-Type: text/plain; charset="
        + charset
        + b"\r\n\r\n"
        + body
        + b"\r\n--"
        + _BOUNDARY
        + b"--\r\n"
    )


def _harness() -> DifferentialHarness:
    return DifferentialHarness(
        candidate=MultipartFormDataNodeTarget().as_command_target(),
        oracle=MultipartFormDataTarget().as_command_target(),
        timeout_seconds=5.0,
        max_input_bytes=512 * 1024,
        max_output_bytes=2 * 1024 * 1024,
        max_total_output_bytes=4 * 1024 * 1024,
    )


def test_charset_mutations_are_deterministic_and_preserve_text_semantics() -> None:
    seed = _text_part("café".encode())

    first = tuple(multipart_form_data_charset_mutations(seed))
    second = tuple(multipart_form_data_charset_mutations(seed))

    assert first == second
    assert first == (_text_part("café".encode("iso-8859-1"), charset=b"iso-8859-1"),)


def test_charset_mutations_fail_closed_on_untrusted_shape_and_budget() -> None:
    with pytest.raises(ValueError):
        tuple(multipart_form_data_charset_mutations(b"not multipart"))
    with pytest.raises(ValueError, match="byte budget"):
        tuple(multipart_form_data_charset_mutations(b"x" * (64 * 1024 + 1)))


def test_real_targets_discover_charset_policy_mismatch_from_matching_seed() -> None:
    harness = _harness()
    seed = _text_part("café".encode())
    cases = (seed, *multipart_form_data_charset_mutations(seed))

    assert harness.compare(seed).classification == "match"
    discovery = run_failure_discovery_campaign(
        cases=cases.__getitem__,
        evaluate=harness.compare,
        max_evaluations=len(cases),
        max_unique_failures=1,
    )

    assert discovery.evaluations == 2
    assert len(discovery.failures) == 1
    failure = discovery.failures[0]
    assert failure.evaluation_index == 1
    assert failure.signature.kind == "product_mismatch"
    assert failure.signature.dimensions == ("stdout",)
    assert b"charset=iso-8859-1" in failure.case
