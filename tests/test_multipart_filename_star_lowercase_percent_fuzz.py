from __future__ import annotations

import pytest

from systems_conformance import (
    DifferentialHarness,
    MultipartFormDataNodeTarget,
    MultipartFormDataTarget,
    run_failure_discovery_campaign,
)
from systems_conformance.multipart_form_data_adapter import MULTIPART_FORM_DATA_BOUNDARY
from systems_conformance.multipart_form_data_fuzz import (
    multipart_form_data_filename_star_lowercase_percent_mutations,
)

_BOUNDARY = MULTIPART_FORM_DATA_BOUNDARY.encode("ascii")


def _file_part(filename_parameter: bytes) -> bytes:
    return (
        b"--"
        + _BOUNDARY
        + b'\r\nContent-Disposition: form-data; name="f"; '
        + filename_parameter
        + b"\r\nContent-Type: text/plain\r\n\r\nabc\r\n--"
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


def test_lowercase_percent_mutation_is_deterministic_and_semantic_preserving() -> None:
    seed = _file_part(b'filename="plain.txt"')
    expected = _file_part(b"filename*=UTF-8''%70%6c%61%69%6e%2e%74%78%74")

    first = tuple(multipart_form_data_filename_star_lowercase_percent_mutations(seed))
    second = tuple(multipart_form_data_filename_star_lowercase_percent_mutations(seed))

    assert first == second == (expected,)


def test_lowercase_percent_mutation_keeps_fail_closed_bounds() -> None:
    with pytest.raises(ValueError):
        tuple(multipart_form_data_filename_star_lowercase_percent_mutations(b"not multipart"))
    with pytest.raises(ValueError, match="byte budget"):
        tuple(
            multipart_form_data_filename_star_lowercase_percent_mutations(
                b"x" * (64 * 1024 + 1)
            )
        )
    assert tuple(
        multipart_form_data_filename_star_lowercase_percent_mutations(
            _file_part(b'filename="semi;colon.txt"')
        )
    ) == ()
    assert tuple(
        multipart_form_data_filename_star_lowercase_percent_mutations(
            _file_part(b"filename*=UTF-8''%70%6c%61%69%6e%2e%74%78%74")
        )
    ) == ()


def test_real_targets_discover_lowercase_percent_filename_star_mismatch() -> None:
    harness = _harness()
    seed = _file_part(b'filename="plain.txt"')
    cases = (
        seed,
        *multipart_form_data_filename_star_lowercase_percent_mutations(seed),
    )

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
    assert b"filename*=UTF-8''%70%6c%61%69%6e%2e%74%78%74" in failure.case
