import errno
import tempfile

import pytest

from systems_conformance import FaultingFileSync, FaultSpec


def test_file_sync_rejects_unsupported_fault_contract() -> None:
    with tempfile.TemporaryFile("w+b") as sink:
        with pytest.raises(ValueError, match="operation='fsync'"):
            FaultingFileSync(sink, FaultSpec("write", 0, "io_error"))
        with pytest.raises(ValueError, match="unsupported file sync fault kind"):
            FaultingFileSync(sink, FaultSpec("fsync", 0, "short_write"))


def test_file_sync_injects_exact_occurrence_and_recovers() -> None:
    with tempfile.TemporaryFile("w+b") as sink:
        sink.write(b"durable-before-fault")
        syncer = FaultingFileSync(sink, FaultSpec("fsync", 1, "io_error"))

        syncer.sync()
        assert not syncer.triggered

        sink.write(b"-buffered-before-eio")
        with pytest.raises(OSError) as exc_info:
            syncer.sync()
        assert exc_info.value.errno == errno.EIO
        assert syncer.triggered

        syncer.sync()
        sink.seek(0)
        assert sink.read() == b"durable-before-fault-buffered-before-eio"
