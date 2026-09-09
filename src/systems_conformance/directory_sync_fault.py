from __future__ import annotations

import errno
import os
from os import PathLike

from .fault import FaultController, FaultSpec


class FaultingDirectorySync:
    """Inject one deterministic I/O failure at a real directory sync boundary."""

    __slots__ = ("_controller",)

    def __init__(self, spec: FaultSpec) -> None:
        if spec.operation != "dir_fsync":
            raise ValueError("directory sync only supports operation='dir_fsync'")
        if spec.kind != "io_error":
            raise ValueError(f"unsupported directory sync fault kind: {spec.kind}")
        if os.name == "nt":
            raise NotImplementedError("directory fsync is not supported on Windows")
        self._controller = FaultController(spec)

    @property
    def triggered(self) -> bool:
        return self._controller.triggered

    def sync(self, directory: str | bytes | PathLike[str] | PathLike[bytes]) -> None:
        """Sync directory metadata unless this occurrence injects EIO."""

        fault = self._controller.checkpoint("dir_fsync")
        if fault is not None:
            raise OSError(errno.EIO, "injected directory sync fault")

        flags = os.O_RDONLY
        directory_flag = getattr(os, "O_DIRECTORY", 0)
        fd = os.open(directory, flags | directory_flag)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
