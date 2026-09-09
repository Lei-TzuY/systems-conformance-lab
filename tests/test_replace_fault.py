import errno
from pathlib import Path

import pytest

from systems_conformance import FaultingAtomicReplace, FaultSpec


def test_atomic_replace_rejects_unsupported_fault_contract() -> None:
    with pytest.raises(ValueError, match="operation='replace'"):
        FaultingAtomicReplace(FaultSpec("write", 0, "io_error"))
    with pytest.raises(ValueError, match="unsupported atomic replace fault kind"):
        FaultingAtomicReplace(FaultSpec("replace", 0, "short_write"))


def test_atomic_replace_injects_exact_occurrence_and_recovers(tmp_path: Path) -> None:
    destination = tmp_path / "published.bin"
    destination.write_bytes(b"generation-0")
    replacer = FaultingAtomicReplace(FaultSpec("replace", 1, "io_error"))

    first = tmp_path / "first.tmp"
    first.write_bytes(b"generation-1")
    replacer.replace(first, destination)
    assert destination.read_bytes() == b"generation-1"
    assert not first.exists()
    assert not replacer.triggered

    faulted = tmp_path / "faulted.tmp"
    faulted.write_bytes(b"generation-2")
    with pytest.raises(OSError) as exc_info:
        replacer.replace(faulted, destination)
    assert exc_info.value.errno == errno.EIO
    assert replacer.triggered
    assert destination.read_bytes() == b"generation-1"
    assert faulted.read_bytes() == b"generation-2"

    recovered = tmp_path / "recovered.tmp"
    recovered.write_bytes(b"generation-3")
    replacer.replace(recovered, destination)
    assert destination.read_bytes() == b"generation-3"
    assert not recovered.exists()
