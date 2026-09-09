import errno
import os
import sys

import pytest

from systems_conformance import (
    CommandTarget,
    DifferentialHarness,
    FaultSpec,
    export_durable_repro_archive,
    import_repro_archive,
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


@pytest.mark.skipif(os.name == "nt", reason="directory fsync is not portable on Windows")
def test_durable_export_replays_real_process_repro(tmp_path) -> None:
    harness = DifferentialHarness(candidate=target(BUGGY_SCRIPT), oracle=target(ECHO_SCRIPT))
    original = harness.write_repro(
        tmp_path / "original",
        input_bytes=b"BUG-durable",
        metadata={"source": "durable-archive-integration"},
    )

    archive = export_durable_repro_archive(original.path, tmp_path / "durable.zip")
    imported = import_repro_archive(archive, tmp_path / "imported")
    replay = harness.replay_repro(imported.path)

    assert replay.reproduced
    assert replay.run.signature == replay.bundle.signature
    assert replay.bundle.metadata == {"source": "durable-archive-integration"}


@pytest.mark.skipif(os.name == "nt", reason="directory fsync is not portable on Windows")
def test_file_sync_fault_prevents_archive_publication(tmp_path) -> None:
    harness = DifferentialHarness(candidate=target(BUGGY_SCRIPT), oracle=target(ECHO_SCRIPT))
    original = harness.write_repro(
        tmp_path / "original",
        input_bytes=b"BUG-file-sync",
        metadata={"source": "durable-file-sync-fault"},
    )
    destination = tmp_path / "durable.zip"

    with pytest.raises(OSError) as error:
        export_durable_repro_archive(
            original.path,
            destination,
            file_sync_spec=FaultSpec("fsync", 0, "io_error"),
        )

    assert error.value.errno == errno.EIO
    assert not destination.exists()
    assert not list(tmp_path.glob(".durable.zip.export-*.tmp"))


@pytest.mark.skipif(os.name == "nt", reason="directory fsync is not portable on Windows")
def test_directory_sync_fault_reports_post_publication_state(tmp_path) -> None:
    harness = DifferentialHarness(candidate=target(BUGGY_SCRIPT), oracle=target(ECHO_SCRIPT))
    original = harness.write_repro(
        tmp_path / "original",
        input_bytes=b"BUG-directory-sync",
        metadata={"source": "durable-directory-sync-fault"},
    )
    destination = tmp_path / "durable.zip"

    with pytest.raises(OSError) as error:
        export_durable_repro_archive(
            original.path,
            destination,
            directory_sync_spec=FaultSpec("dir_fsync", 0, "io_error"),
        )

    assert error.value.errno == errno.EIO
    assert destination.is_file()
    assert not list(tmp_path.glob(".durable.zip.export-*.tmp"))

    imported = import_repro_archive(destination, tmp_path / "imported")
    replay = harness.replay_repro(imported.path)
    assert replay.reproduced
    assert replay.bundle.metadata == {"source": "durable-directory-sync-fault"}


@pytest.mark.skipif(os.name != "nt", reason="Windows-specific fail-closed contract")
def test_durable_export_fails_closed_before_windows_publication(tmp_path) -> None:
    harness = DifferentialHarness(candidate=target(BUGGY_SCRIPT), oracle=target(ECHO_SCRIPT))
    original = harness.write_repro(
        tmp_path / "original",
        input_bytes=b"BUG-windows",
        metadata={"source": "durable-windows-fail-closed"},
    )
    destination = tmp_path / "durable.zip"

    with pytest.raises(NotImplementedError, match="directory fsync"):
        export_durable_repro_archive(original.path, destination)

    assert not destination.exists()
