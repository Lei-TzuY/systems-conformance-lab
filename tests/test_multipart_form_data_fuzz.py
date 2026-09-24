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
    multipart_form_data_charset_mutations,
    multipart_form_data_filename_star_language_mutations,
    multipart_form_data_filename_star_mutations,
    multipart_form_data_filename_star_percent_mutations,
)

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


def _file_part(filename_parameter: bytes) -> bytes:
    return (
        b"--"
        + _BOUNDARY
        + b"\r\nContent-Disposition: form-data; name=\"f\"; "
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


def test_filename_star_mutations_are_deterministic_and_preserve_filename() -> None:
    seed = _file_part(b'filename="plain.txt"')
    expected = _file_part(b"filename*=UTF-8''plain.txt")

    first = tuple(multipart_form_data_filename_star_mutations(seed))
    second = tuple(multipart_form_data_filename_star_mutations(seed))

    assert first == second
    assert first == (expected,)


def test_filename_star_mutations_fail_closed_and_skip_ambiguous_names() -> None:
    with pytest.raises(ValueError):
        tuple(multipart_form_data_filename_star_mutations(b"not multipart"))
    with pytest.raises(ValueError, match="byte budget"):
        tuple(multipart_form_data_filename_star_mutations(b"x" * (64 * 1024 + 1)))

    assert tuple(
        multipart_form_data_filename_star_mutations(
            _file_part(b'filename="semi;colon.txt"')
        )
    ) == ()
    assert tuple(
        multipart_form_data_filename_star_mutations(
            _file_part(b"filename*=UTF-8''already.txt")
        )
    ) == ()


def test_real_targets_discover_filename_star_policy_mismatch_from_matching_seed() -> None:
    harness = _harness()
    seed = _file_part(b'filename="plain.txt"')
    cases = (seed, *multipart_form_data_filename_star_mutations(seed))

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
    assert b"filename*=UTF-8''plain.txt" in failure.case


def test_filename_star_percent_mutations_are_deterministic_and_preserve_filename() -> None:
    seed = _file_part(b'filename="plain.txt"')
    expected = _file_part(b"filename*=UTF-8''%70%6C%61%69%6E%2E%74%78%74")

    first = tuple(multipart_form_data_filename_star_percent_mutations(seed))
    second = tuple(multipart_form_data_filename_star_percent_mutations(seed))

    assert first == second
    assert first == (expected,)


def test_filename_star_percent_mutations_share_fail_closed_bounds() -> None:
    with pytest.raises(ValueError):
        tuple(multipart_form_data_filename_star_percent_mutations(b"not multipart"))
    with pytest.raises(ValueError, match="byte budget"):
        tuple(multipart_form_data_filename_star_percent_mutations(b"x" * (64 * 1024 + 1)))
    assert tuple(
        multipart_form_data_filename_star_percent_mutations(
            _file_part(b'filename="semi;colon.txt"')
        )
    ) == ()


def test_real_targets_discover_percent_encoded_filename_star_mismatch() -> None:
    harness = _harness()
    seed = _file_part(b'filename="plain.txt"')
    cases = (seed, *multipart_form_data_filename_star_percent_mutations(seed))

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
    assert b"filename*=UTF-8''%70%6C%61%69%6E%2E%74%78%74" in failure.case


def test_filename_star_language_mutations_are_deterministic_and_preserve_filename() -> None:
    seed = _file_part(b'filename="plain.txt"')
    expected = _file_part(b"filename*=UTF-8'en'%70%6C%61%69%6E%2E%74%78%74")

    first = tuple(multipart_form_data_filename_star_language_mutations(seed))
    second = tuple(multipart_form_data_filename_star_language_mutations(seed))

    assert first == second
    assert first == (expected,)


def test_filename_star_language_mutations_share_fail_closed_bounds() -> None:
    with pytest.raises(ValueError):
        tuple(multipart_form_data_filename_star_language_mutations(b"not multipart"))
    with pytest.raises(ValueError, match="byte budget"):
        tuple(multipart_form_data_filename_star_language_mutations(b"x" * (64 * 1024 + 1)))
    assert tuple(
        multipart_form_data_filename_star_language_mutations(
            _file_part(b'filename="semi;colon.txt"')
        )
    ) == ()


def test_real_targets_discover_filename_star_language_policy_mismatch() -> None:
    harness = _harness()
    seed = _file_part(b'filename="plain.txt"')
    cases = (seed, *multipart_form_data_filename_star_language_mutations(seed))

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
    assert b"filename*=UTF-8'en'%70%6C%61%69%6E%2E%74%78%74" in failure.case
