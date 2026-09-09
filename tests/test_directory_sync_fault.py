import errno
import os
from pathlib import Path

import pytest

from systems_conformance.directory_sync_fault import FaultingDirectorySync
from systems_conformance.fault import FaultSpec


def test_directory_sync_rejects_unsupported_fault_contract() -> None:
    if os.name == "nt":
        pytest.skip("directory fsync is not supported on Windows")
    with pytest.raises(ValueError, match="operation='dir_fsync'"):
        FaultingDirectorySync(FaultSpec("fsync", 0, "io_error"))
    with pytest.raises(ValueError, match="unsupported directory sync fault kind"):
        FaultingDirectorySync(FaultSpec("dir_fsync", 0, "short_write"))


def test_directory_sync_fails_closed_on_windows() -> None:
    if os.name != "nt":
        pytest.skip("Windows-only contract")
    with pytest.raises(NotImplementedError, match="not supported on Windows"):
        FaultingDirectorySync(FaultSpec("dir_fsync", 0, "io_error"))


def test_directory_sync_injects_exact_occurrence_and_recovers(tmp_path: Path) -> None:
    if os.name == "nt":
        pytest.skip("directory fsync is not supported on Windows")

    syncer = FaultingDirectorySync(FaultSpec("dir_fsync", 1, "io_error"))

    (tmp_path / "generation-1").write_bytes(b"one")
    syncer.sync(tmp_path)
    assert not syncer.triggered

    (tmp_path / "generation-2").write_bytes(b"two")
    with pytest.raises(OSError) as exc_info:
        syncer.sync(tmp_path)
    assert exc_info.value.errno == errno.EIO
    assert syncer.triggered

    (tmp_path / "generation-3").write_bytes(b"three")
    syncer.sync(tmp_path)
    assert sorted(path.name for path in tmp_path.iterdir()) == [
        "generation-1",
        "generation-2",
        "generation-3",
    ]
