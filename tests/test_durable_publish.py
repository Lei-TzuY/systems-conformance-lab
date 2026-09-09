import errno
import os
from pathlib import Path

import pytest

from systems_conformance.durable_publish import FaultingDurableFilePublisher
from systems_conformance.fault import FaultSpec


def _publisher(fault_stage: str) -> FaultingDurableFilePublisher:
    occurrence = {"fsync": 99, "replace": 99, "dir_fsync": 99}
    occurrence[fault_stage] = 0
    return FaultingDurableFilePublisher(
        file_sync_spec=FaultSpec("fsync", occurrence["fsync"], "io_error"),
        replace_spec=FaultSpec("replace", occurrence["replace"], "io_error"),
        directory_sync_spec=FaultSpec("dir_fsync", occurrence["dir_fsync"], "io_error"),
    )


@pytest.mark.skipif(os.name == "nt", reason="directory fsync is not supported on Windows")
def test_durable_publisher_rejects_cross_directory_staging(tmp_path: Path) -> None:
    other = tmp_path / "other"
    other.mkdir()
    publisher = _publisher("replace")

    with pytest.raises(ValueError, match="share a parent"):
        publisher.publish(other / "stage", tmp_path / "live", b"new")


@pytest.mark.skipif(os.name == "nt", reason="directory fsync is not supported on Windows")
@pytest.mark.parametrize("fault_stage", ["fsync", "replace", "dir_fsync"])
def test_durable_publisher_exercises_real_filesystem_fault_boundaries(
    tmp_path: Path, fault_stage: str
) -> None:
    destination = tmp_path / "live.bin"
    source = tmp_path / "stage.bin"
    destination.write_bytes(b"old")
    publisher = _publisher(fault_stage)

    with pytest.raises(OSError) as exc_info:
        publisher.publish(source, destination, b"new")

    assert exc_info.value.errno == errno.EIO
    if fault_stage in {"fsync", "replace"}:
        assert destination.read_bytes() == b"old"
        assert source.exists()
    else:
        # Publication happened before the directory durability checkpoint failed.
        assert destination.read_bytes() == b"new"
        assert not source.exists()
