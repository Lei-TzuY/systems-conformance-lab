import errno
import os
import sys

import pytest

from systems_conformance import (
    CommandTarget,
    DifferentialHarness,
    FaultSpec,
    export_repro_archive,
    import_durable_repro_archive,
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


def make_archive(tmp_path):
    harness = DifferentialHarness(candidate=target(BUGGY_SCRIPT), oracle=target(ECHO_SCRIPT))
    original = harness.write_repro(
        tmp_path / "original",
        input_bytes=b"BUG-durable-import",
        metadata={"source": "durable-import-integration"},
    )
    archive = export_repro_archive(original.path, tmp_path / "repro.zip")
    return harness, archive


@pytest.mark.skipif(os.name == "nt", reason="directory fsync is not portable on Windows")
def test_durable_import_replays_real_process_repro(tmp_path) -> None:
    harness, archive = make_archive(tmp_path)

    imported = import_durable_repro_archive(archive, tmp_path / "imported")
    replay = harness.replay_repro(imported.path)

    assert replay.reproduced
    assert replay.run.signature == replay.bundle.signature
    assert replay.bundle.metadata == {"source": "durable-import-integration"}
    assert not list(tmp_path.glob(".imported.durable-import-*"))


@pytest.mark.skipif(os.name == "nt", reason="directory fsync is not portable on Windows")
@pytest.mark.parametrize("occurrence", [0, 1, 2])
def test_prepublication_sync_fault_leaves_no_destination(tmp_path, occurrence) -> None:
    _, archive = make_archive(tmp_path)
    destination = tmp_path / "imported"

    with pytest.raises(OSError) as error:
        import_durable_repro_archive(
            archive,
            destination,
            sync_fault_spec=FaultSpec("import_sync", occurrence, "io_error"),
        )

    assert error.value.errno == errno.EIO
    assert not destination.exists()
    assert not list(tmp_path.glob(".imported.durable-import-*"))


@pytest.mark.skipif(os.name == "nt", reason="directory fsync is not portable on Windows")
def test_parent_sync_fault_reports_postpublication_state(tmp_path) -> None:
    harness, archive = make_archive(tmp_path)
    destination = tmp_path / "imported"

    with pytest.raises(OSError) as error:
        import_durable_repro_archive(
            archive,
            destination,
            sync_fault_spec=FaultSpec("import_sync", 3, "io_error"),
        )

    assert error.value.errno == errno.EIO
    assert destination.is_dir()
    replay = harness.replay_repro(destination)
    assert replay.reproduced
    assert replay.bundle.metadata == {"source": "durable-import-integration"}
    assert not list(tmp_path.glob(".imported.durable-import-*"))


@pytest.mark.skipif(os.name != "nt", reason="Windows-specific fail-closed contract")
def test_durable_import_fails_closed_before_windows_publication(tmp_path) -> None:
    _, archive = make_archive(tmp_path)
    destination = tmp_path / "imported"

    with pytest.raises(NotImplementedError, match="directory fsync"):
        import_durable_repro_archive(archive, destination)

    assert not destination.exists()
    assert not list(tmp_path.glob(".imported.durable-import-*"))
