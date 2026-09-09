from __future__ import annotations

import errno
import os
from os import PathLike

from .fault import FaultController, FaultSpec


class FaultingAtomicReplace:
    """Inject one deterministic I/O failure at a real atomic replace boundary.

    ``replace`` delegates successful occurrences to ``os.replace`` so the adapter
    exercises the host filesystem's pathname publication primitive. The caller is
    responsible for writing and syncing the source before publication and for any
    directory durability policy required after publication.
    """

    __slots__ = ("_controller",)

    def __init__(self, spec: FaultSpec) -> None:
        if spec.operation != "replace":
            raise ValueError("atomic replace only supports operation='replace'")
        if spec.kind != "io_error":
            raise ValueError(f"unsupported atomic replace fault kind: {spec.kind}")
        self._controller = FaultController(spec)

    @property
    def triggered(self) -> bool:
        return self._controller.triggered

    def replace(
        self,
        source: str | bytes | PathLike[str] | PathLike[bytes],
        destination: str | bytes | PathLike[str] | PathLike[bytes],
    ) -> None:
        """Atomically replace ``destination`` unless this occurrence injects EIO."""

        fault = self._controller.checkpoint("replace")
        if fault is not None:
            raise OSError(errno.EIO, "injected atomic replace fault")
        os.replace(source, destination)
