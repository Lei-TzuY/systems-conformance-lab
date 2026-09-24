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
from systems_conformance.multipart_form_data_reducer import (
    multipart_form_data_reduction_candidates,
)

_BOUNDARY = MULTIPART_FORM_DATA_BOUNDARY.encode("ascii")


def _part(*, headers: tuple[bytes, ...], body: bytes) -> bytes:
    return (
        b"--"
        + _BOUNDARY
        + b"\r\n"
        + b"\r\n".join(headers)
        + b"\r\n\r\n"
        + body
        + b"\r\n"
    )


def _multipart(*parts: bytes) -> bytes:
    return b"".join(parts) + b"--" + _BOUNDARY + b"--\r\n"


def _text_part(name: str, body: bytes, *, content_type: bytes | None = None) -> bytes:
    headers = [f'Content-Disposition: form-data; name="{name}"'.encode("ascii")]
    if content_type is not None:
        headers.append(b"Content-Type: " + content_type)
    return _part(headers=tuple(headers), body=body)


def _harness() -> DifferentialHarness:
    return DifferentialHarness(
        candidate=MultipartFormDataNodeTarget().as_command_target(),
        oracle=MultipartFormDataTarget().as_command_target(),
        timeout_seconds=5.0,
        max_input_bytes=512 * 1024,
        max_output_bytes=2 * 1024 * 1024,
        max_total_output_bytes=4 * 1024 * 1024,
    )


def test_candidates_are_deterministic_unique_and_strictly_smaller() -> None:
    first_part = _text_part("drop", b"abcdef")
    second_part = _text_part("keep", b"ghij")
    raw = _multipart(first_part, second_part)

    first = tuple(multipart_form_data_reduction_candidates(raw))
    second = tuple(multipart_form_data_reduction_candidates(raw))

    assert first == second
    assert first
    assert len(first) == len(set(first))
    assert all(len(candidate) < len(raw) for candidate in first)
    assert _multipart(second_part) in first
    assert _multipart(first_part) in first
    assert _multipart(_text_part("drop", b""), second_part) in first


@pytest.mark.parametrize(
    "raw",
    [
        b"",
        _multipart(_text_part("x", b"hello")).replace(b"\r\n", b"\n"),
        b"preamble" + _multipart(_text_part("x", b"hello")),
        _multipart(_text_part("x", b"hello")) + b"epilogue",
        b"--" + _BOUNDARY + b"\r\nBrokenHeader\r\n\r\nx\r\n--" + _BOUNDARY + b"--\r\n",
    ],
)
def test_reducer_fails_closed_on_invalid_or_noncanonical_frames(raw: bytes) -> None:
    with pytest.raises(ValueError):
        tuple(multipart_form_data_reduction_candidates(raw))


def test_real_charset_mismatch_reduces_and_replays(tmp_path) -> None:
    harness = _harness()
    witness = _multipart(
        _text_part(
            "x",
            b"padding-padding-\xe9",
            content_type=b"text/plain; charset=iso-8859-1",
        )
    )
    discovery = run_failure_discovery_campaign(
        cases=(witness,).__getitem__,
        evaluate=harness.compare,
        max_evaluations=1,
        max_unique_failures=1,
    )

    assert len(discovery.failures) == 1
    failure = discovery.failures[0]
    assert failure.signature.kind == "product_mismatch"
    assert failure.signature.dimensions == ("stdout",)

    reduced = reduce_failure_to_repro(
        failure,
        harness=harness,
        destination=tmp_path / "multipart-form-data-reduced-repro",
        candidates=multipart_form_data_reduction_candidates,
        metadata={"domain": "multipart-form-data-structural-reducer"},
    )

    assert len(reduced.reduction.reduced) < len(witness)
    replay = harness.replay_repro(reduced.repro.path)
    assert replay.reproduced is True
    assert replay.run.signature == failure.signature
    assert replay.bundle.metadata["domain"] == "multipart-form-data-structural-reducer"


def _percent_filename_part(
    encoded: bytes, body: bytes = b"payload", *, language: bytes = b""
) -> bytes:
    return _part(
        headers=(
            b'Content-Disposition: form-data; name="upload"; filename*=UTF-8\''
            + language
            + b"'"
            + encoded,
            b"Content-Type: application/octet-stream",
        ),
        body=body,
    )


def test_percent_filename_star_payload_reduction_is_bounded_and_policy_preserving() -> None:
    raw = _multipart(_percent_filename_part(b"%70%6C%61%69%6E%2E%74%78%74"))
    candidates = tuple(multipart_form_data_reduction_candidates(raw))

    half = _multipart(_percent_filename_part(b"%70%6C%61%69", body=b"payload"))
    one = _multipart(_percent_filename_part(b"%70", body=b"payload"))
    assert half in candidates
    assert one in candidates
    assert all(b"filename*=UTF-8''" in candidate for candidate in (half, one))
    assert all(len(candidate) < len(raw) for candidate in candidates)


def test_language_filename_star_payload_reduction_preserves_fixed_tag() -> None:
    raw = _multipart(
        _percent_filename_part(b"%70%6C%61%69%6E%2E%74%78%74", language=b"en")
    )
    candidates = tuple(multipart_form_data_reduction_candidates(raw))

    half = _multipart(_percent_filename_part(b"%70%6C%61%69", language=b"en"))
    one = _multipart(_percent_filename_part(b"%70", language=b"en"))
    assert half in candidates
    assert one in candidates
    assert all(b"filename*=UTF-8'en'" in candidate for candidate in (half, one))
    assert all(len(candidate) < len(raw) for candidate in candidates)


@pytest.mark.parametrize(
    "parameter",
    [
        b"filename*=UTF-8''plain.txt",
        b"filename*=UTF-8''%70%6",
        b"filename*=iso-8859-1''%70%6C",
        b"filename*=UTF-8'fr'%70%6C",
        b"filename*=UTF-8'en'plain.txt",
        b"filename*=UTF-8''%70%6C; x=y",
        b"filename*=UTF-8'en'%70%6C; x=y",
    ],
)
def test_filename_star_header_reduction_leaves_other_policy_forms_untouched(parameter: bytes) -> None:
    header = b'Content-Disposition: form-data; name="upload"; ' + parameter
    raw = _multipart(_part(headers=(header,), body=b""))

    assert tuple(multipart_form_data_reduction_candidates(raw)) == ()


def test_real_percent_filename_star_mismatch_reduces_and_replays(tmp_path) -> None:
    harness = _harness()
    witness = _multipart(
        _percent_filename_part(b"%70%6C%61%69%6E%2E%74%78%74", body=b"padding-padding")
    )
    discovery = run_failure_discovery_campaign(
        cases=(witness,).__getitem__,
        evaluate=harness.compare,
        max_evaluations=1,
        max_unique_failures=1,
    )

    assert len(discovery.failures) == 1
    failure = discovery.failures[0]
    assert failure.signature.kind == "product_mismatch"

    reduced = reduce_failure_to_repro(
        failure,
        harness=harness,
        destination=tmp_path / "multipart-filename-star-reduced-repro",
        candidates=multipart_form_data_reduction_candidates,
        metadata={"domain": "multipart-filename-star-percent-reducer"},
    )

    assert len(reduced.reduction.reduced) < len(witness)
    assert b"filename*=UTF-8''%70" in reduced.reduction.reduced
    assert b"%6C%61%69%6E%2E%74%78%74" not in reduced.reduction.reduced
    replay = harness.replay_repro(reduced.repro.path)
    assert replay.reproduced is True
    assert replay.run.signature == failure.signature
    assert replay.bundle.metadata["domain"] == "multipart-filename-star-percent-reducer"


def test_real_language_filename_star_mismatch_reduces_and_replays(tmp_path) -> None:
    harness = _harness()
    witness = _multipart(
        _percent_filename_part(
            b"%70%6C%61%69%6E%2E%74%78%74",
            body=b"padding-padding",
            language=b"en",
        )
    )
    discovery = run_failure_discovery_campaign(
        cases=(witness,).__getitem__,
        evaluate=harness.compare,
        max_evaluations=1,
        max_unique_failures=1,
    )

    assert len(discovery.failures) == 1
    failure = discovery.failures[0]
    assert failure.signature.kind == "product_mismatch"

    reduced = reduce_failure_to_repro(
        failure,
        harness=harness,
        destination=tmp_path / "multipart-filename-star-language-reduced-repro",
        candidates=multipart_form_data_reduction_candidates,
        metadata={"domain": "multipart-filename-star-language-reducer"},
    )

    assert len(reduced.reduction.reduced) < len(witness)
    assert b"filename*=UTF-8'en'%70" in reduced.reduction.reduced
    assert b"%6C%61%69%6E%2E%74%78%74" not in reduced.reduction.reduced
    replay = harness.replay_repro(reduced.repro.path)
    assert replay.reproduced is True
    assert replay.run.signature == failure.signature
    assert replay.bundle.metadata["domain"] == "multipart-filename-star-language-reducer"
