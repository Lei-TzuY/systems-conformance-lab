import hashlib
import sys
import zipfile
from pathlib import Path

import pytest

from systems_conformance import (
    CommandTarget,
    DifferentialHarness,
    export_repro_archive,
    replay_repro_archive,
)

ECHO_SCRIPT = (
    "import sys; data = sys.stdin.buffer.read(); sys.stdout.buffer.write(data)"
)
BUGGY_SCRIPT = (
    "import sys; data = sys.stdin.buffer.read(); "
    "sys.stdout.buffer.write(data.replace(b'BUG', b'BAD') if b'BUG' in data else data)"
)


def target(script: str) -> CommandTarget:
    return CommandTarget((sys.executable, "-c", script))


def marker_script(marker: Path, *, buggy: bool) -> str:
    transform = (
        "data.replace(b'BUG', b'BAD') if b'BUG' in data else data"
        if buggy
        else "data"
    )
    return (
        "import pathlib, sys; "
        f"pathlib.Path({str(marker)!r}).write_text('ran'); "
        "data = sys.stdin.buffer.read(); "
        f"sys.stdout.buffer.write({transform})"
    )


def test_archive_replay_round_trips_real_process_failure(tmp_path) -> None:
    harness = DifferentialHarness(candidate=target(BUGGY_SCRIPT), oracle=target(ECHO_SCRIPT))
    repro = harness.write_repro(
        tmp_path / "bundle",
        input_bytes=b"BUG-portable",
        metadata={"source": "archive-replay-integration"},
    )
    archive = export_repro_archive(repro.path, tmp_path / "portable.zip")
    archive_sha256 = hashlib.sha256(archive.read_bytes()).hexdigest()

    replay = replay_repro_archive(
        harness,
        archive,
        expected_archive_sha256=archive_sha256,
        require_reproduction=True,
    )

    assert replay.archive_path == archive
    assert replay.archive_sha256 == archive_sha256
    assert replay.input_bytes == b"BUG-portable"
    assert replay.metadata == {"source": "archive-replay-integration"}
    assert replay.replay_context_sha256 == harness.replay_context_sha256
    assert replay.reproduced
    assert replay.run.signature == replay.signature


def test_archive_replay_rejects_transport_digest_drift_before_target_execution(
    tmp_path,
) -> None:
    marker = tmp_path / "executed"
    candidate = target(marker_script(marker, buggy=True))
    oracle = target(marker_script(marker, buggy=False))
    harness = DifferentialHarness(candidate=candidate, oracle=oracle)
    repro = harness.write_repro(tmp_path / "bundle", input_bytes=b"BUG")
    archive = export_repro_archive(repro.path, tmp_path / "portable.zip")
    marker.unlink()

    with pytest.raises(ValueError, match="sha256 does not match expected digest"):
        replay_repro_archive(
            harness,
            archive,
            expected_archive_sha256="0" * 64,
            require_reproduction=True,
        )

    assert not marker.exists()


def test_archive_replay_rejects_invalid_expected_transport_digest(tmp_path) -> None:
    harness = DifferentialHarness(candidate=target(ECHO_SCRIPT), oracle=target(ECHO_SCRIPT))
    archive = tmp_path / "portable.zip"
    archive.write_bytes(b"not-read")

    with pytest.raises(
        ValueError,
        match="expected_archive_sha256 must be a lowercase SHA-256 hex digest",
    ):
        replay_repro_archive(harness, archive, expected_archive_sha256="ABC")


def test_archive_replay_strict_gate_rejects_real_process_signature_drift(tmp_path) -> None:
    original = DifferentialHarness(candidate=target(BUGGY_SCRIPT), oracle=target(ECHO_SCRIPT))
    repro = original.write_repro(tmp_path / "bundle", input_bytes=b"BUG-portable")
    archive = export_repro_archive(repro.path, tmp_path / "portable.zip")

    fixed = DifferentialHarness(candidate=target(ECHO_SCRIPT), oracle=target(ECHO_SCRIPT))
    with pytest.raises(
        RuntimeError,
        match="portable repro archive did not reproduce archived failure signature",
    ):
        replay_repro_archive(
            fixed,
            archive,
            require_same_context=False,
            require_reproduction=True,
        )

    replay = replay_repro_archive(
        fixed,
        archive,
        require_same_context=False,
        require_reproduction=False,
    )
    assert not replay.reproduced
    assert replay.signature is not None
    assert replay.run.signature is None


def test_archive_replay_rejects_context_drift_before_target_execution(tmp_path) -> None:
    marker = tmp_path / "executed"
    candidate = target(marker_script(marker, buggy=True))
    oracle = target(marker_script(marker, buggy=False))
    harness = DifferentialHarness(candidate=candidate, oracle=oracle)
    repro = harness.write_repro(tmp_path / "bundle", input_bytes=b"BUG")
    archive = export_repro_archive(repro.path, tmp_path / "portable.zip")
    marker.unlink()

    changed = DifferentialHarness(
        candidate=candidate,
        oracle=oracle,
        max_output_bytes=harness.max_output_bytes - 1,
    )
    with pytest.raises(ValueError, match="repro replay context does not match"):
        replay_repro_archive(
            changed,
            archive,
            require_reproduction=True,
        )

    assert not marker.exists()


def test_archive_replay_rejects_invalid_archive_before_target_execution(tmp_path) -> None:
    marker = tmp_path / "executed"
    script = marker_script(marker, buggy=False)
    harness = DifferentialHarness(candidate=target(script), oracle=target(script))
    archive = tmp_path / "invalid.zip"
    with zipfile.ZipFile(archive, mode="w", compression=zipfile.ZIP_STORED) as writer:
        writer.writestr("input.bin", b"untrusted")
        writer.writestr("manifest.json", b"{}")

    with pytest.raises(ValueError, match="fields do not match v1 schema"):
        replay_repro_archive(
            harness,
            archive,
            require_reproduction=True,
        )

    assert not marker.exists()
