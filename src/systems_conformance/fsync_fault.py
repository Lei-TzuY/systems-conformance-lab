from __future__ import annotations

import errno
import os
from typing import BinaryIO

from .fault import FaultController, FaultSpec


class FaultingFileSync:
    """Inject one deterministic durability fault at a real file ``fsync`` boundary.

    The caller retains ownership of ``sink``. Each ``sync`` first flushes Python's
    userspace buffer, then applies the configured checkpoint, and otherwise calls
    ``os.fsync`` on the stream's file descriptor. The adapter deliberately models
    only an ``EIO`` failure at ``operation='fsync'``; crash semantics and filesystem
    recovery policy remain target-specific concerns above this boundary.
    """

    __slots__ = ("_controller", "_sink")

    def __init__(self, sink: BinaryIO, spec: FaultSpec) -> None:
        if spec.operation != "fsync":
            raise ValueError("file sync only supports operation='fsync'")
        if spec.kind != "io_error":
            raise ValueError(f"unsupported file sync fault kind: {spec.kind}")

        self._sink = sink
        self._controller = FaultController(spec)

    @property
    def triggered(self) -> bool:
        return self._controller.triggered

    def sync(self) -> None:
        """Flush buffered bytes and fsync unless this occurrence injects EIO."""

        self._sink.flush()
        fault = self._controller.checkpoint("fsync")
        if fault is not None:
            raise OSError(errno.EIO, "injected file sync fault")
        os.fsync(self._sink.fileno())
