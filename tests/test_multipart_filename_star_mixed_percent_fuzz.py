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
    multipart_form_data_filename_star_mixed_percent_mutations,
)
from systems_conformance.multipart_form_data_reducer import (
    multipart_form_data_reduction_candidates,
)

_BOUNDARY = MULTIPART_FORM_DATA_BOUNDARY.encode("ascii")


def _file_part(filename_parameter: bytes, *, body: bytes = b"abc") -> bytes:
    return (
        b"--"
        + _BOUNDARY
        + b'\r\nContent-Disposition: form-data; name="f"; '
        + filename_parameter
        + b"\r\nContent-Type: text/plain\r\n\r\n"
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


def test_mixed_percent_mutation_is_deterministic_and_semantic_preserving() -> None:
    seed = _file_part(b'filename="plain.txt"')
    expected = _file_part(b"filename*=UTF-8''%70lain.txt")

    first = tuple(multipart_form_data_filename_star_mixed_percent_mutations(seed))
    second = tuple(multipart_form_data_filename_star_mixed_percent_mutations(seed))

    assert first == second == (expected,)


def test_mixed_percent_mutation_keeps_fail_closed_bounds() -> None:
    with pytest.raises(ValueError):
        tuple(multipart_form_data_filename_star_mixed_percent_mutations(b"not multipart"))
    with pytest.raises(ValueError, match="byte budget"):
        tuple(
            multipart_form_data_filename_star_mixed_percent_mutations(
                b"x" * (64 * 1024 + 1)
            )
        )
    assert tuple(
        multipart_form_data_filename_star_mixed_percent_mutations(
            _file_part(b'filename="p a.txt"')
        )
    ) == ()
    assert tuple(
        multipart_form_data_filename_star_mixed_percent_mutations(
            _file_part(b'filename="p"')
        )
    ) == ()
    assert tuple(
        multipart_form_data_filename_star_mixed_percent_mutations(
            _file_part(b"filename*=UTF-8''%70lain.txt")
        )
    ) == ()


def test_mixed_percent_reducer_preserves_representation_boundary() -> None:
    raw = _file_part(b"filename*=UTF-8''%70lain.txt", body=b"")
    candidates = tuple(multipart_form_data_reduction_candidates(raw))

    assert _file_part(b"filename*=UTF-8''%70l", body=b"") in candidates
    assert all(b"filename*=UTF-8''%70" not in candidate for candidate in candidates)
    assert tuple(
        multipart_form_data_reduction_candidates(
            _file_part(b"filename*=UTF-8'en'%70lain.txt", body=b"")
        )
    ) == ()


def test_real_targets_discover_mixed_percent_filename_star_mismatch() -> None:
    harness = _harness()
    seed = _file_part(b'filename="plain.txt"')
    cases = (seed, *multipart_form_data_filename_star_mixed_percent_mutations(seed))

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
    assert b"filename*=UTF-8''%70lain.txt" in failure.case


def test_mixed_percent_discovery_reduces_and_replays(tmp_path) -> None:
    harness = _harness()
    seed = _file_part(b'filename="plain.txt"', body=b"padding-padding")
    cases = (seed, *multipart_form_data_filename_star_mixed_percent_mutations(seed))
    discovery = run_failure_discovery_campaign(
        cases=cases.__getitem__,
        evaluate=harness.compare,
        max_evaluations=len(cases),
        max_unique_failures=1,
    )
    assert len(discovery.failures) == 1
    failure = discovery.failures[0]

    reduced = reduce_failure_to_repro(
        failure,
        harness=harness,
        destination=tmp_path / "multipart-filename-star-mixed-percent-repro",
        candidates=multipart_form_data_reduction_candidates,
        metadata={"domain": "multipart-filename-star-mixed-percent"},
    )

    assert b"filename*=UTF-8''%70l" in reduced.reduction.reduced
    assert b"ain.txt" not in reduced.reduction.reduced
    replay = harness.replay_repro(reduced.repro.path)
    assert replay.reproduced is True
    assert replay.run.signature == failure.signature
    assert replay.bundle.metadata["domain"] == "multipart-filename-star-mixed-percent"
