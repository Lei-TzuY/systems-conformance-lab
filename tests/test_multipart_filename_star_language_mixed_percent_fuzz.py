from __future__ import annotations

import pytest

from systems_conformance import (
    DifferentialHarness,
    MultipartFormDataNodeTarget,
    MultipartFormDataTarget,
    reduce_failure_to_repro,
    run_failure_discovery_campaign,
)
from systems_conformance.multipart_form_data_adapter import MULTIPART_FORM_DATA_BOUNDARY
from systems_conformance.multipart_form_data_fuzz import (
    multipart_form_data_filename_star_language_mixed_percent_mutations,
)
from systems_conformance.multipart_form_data_reducer import multipart_form_data_reduction_candidates

_BOUNDARY = MULTIPART_FORM_DATA_BOUNDARY.encode("ascii")


def _file_part(filename_parameter: bytes, *, body: bytes = b"abc") -> bytes:
    return (
        b"--" + _BOUNDARY
        + b'\r\nContent-Disposition: form-data; name="f"; ' + filename_parameter
        + b"\r\nContent-Type: text/plain\r\n\r\n" + body
        + b"\r\n--" + _BOUNDARY + b"--\r\n"
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


def test_language_mixed_mutation_is_deterministic_and_bounded() -> None:
    seed = _file_part(b'filename="plain.txt"')
    expected = _file_part(b"filename*=UTF-8'en'%70lain.txt")
    first = tuple(multipart_form_data_filename_star_language_mixed_percent_mutations(seed))
    second = tuple(multipart_form_data_filename_star_language_mixed_percent_mutations(seed))
    assert first == second == (expected,)
    with pytest.raises(ValueError):
        tuple(multipart_form_data_filename_star_language_mixed_percent_mutations(b"bad"))
    assert tuple(
        multipart_form_data_filename_star_language_mixed_percent_mutations(
            _file_part(b'filename="p a.txt"')
        )
    ) == ()


def test_language_mixed_reducer_preserves_language_and_representation() -> None:
    raw = _file_part(b"filename*=UTF-8'en'%70lain.txt", body=b"")
    candidates = tuple(multipart_form_data_reduction_candidates(raw))
    assert _file_part(b"filename*=UTF-8'en'%70l", body=b"") in candidates
    assert _file_part(b"filename*=UTF-8'en'%70", body=b"") not in candidates
    assert all(b"UTF-8'en'" in candidate for candidate in candidates)


def test_real_targets_discover_reduce_and_replay_language_mixed_mismatch(tmp_path) -> None:
    harness = _harness()
    seed = _file_part(b'filename="plain.txt"', body=b"padding-padding")
    cases = (seed, *multipart_form_data_filename_star_language_mixed_percent_mutations(seed))
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
    assert failure.signature.kind == "product_mismatch"
    assert b"filename*=UTF-8'en'%70lain.txt" in failure.case

    reduced = reduce_failure_to_repro(
        failure,
        harness=harness,
        destination=tmp_path / "multipart-filename-star-language-mixed-repro",
        candidates=multipart_form_data_reduction_candidates,
        metadata={"domain": "multipart-filename-star-language-mixed"},
    )
    assert b"filename*=UTF-8'en'%70l" in reduced.reduction.reduced
    assert b"ain.txt" not in reduced.reduction.reduced
    replay = harness.replay_repro(reduced.repro.path)
    assert replay.reproduced is True
    assert replay.run.signature == failure.signature
