from __future__ import annotations

from os import PathLike
from pathlib import Path

from .directory_sync_fault import FaultingDirectorySync
from .fault import FaultSpec
from .fsync_fault import FaultingFileSync
from .replace_fault import FaultingAtomicReplace


class FaultingDurableFilePublisher:
    """Publish bytes through real file-sync, replace, and directory-sync boundaries."""

    __slots__ = ("_directory_sync", "_file_sync_spec", "_replace")

    def __init__(
        self,
        *,
        file_sync_spec: FaultSpec,
        replace_spec: FaultSpec,
        directory_sync_spec: FaultSpec,
    ) -> None:
        self._file_sync_spec = file_sync_spec
        self._replace = FaultingAtomicReplace(replace_spec)
        self._directory_sync = FaultingDirectorySync(directory_sync_spec)

    def publish(
        self,
        source: str | PathLike[str],
        destination: str | PathLike[str],
        payload: bytes,
    ) -> None:
        """Write and durably publish ``payload`` using an explicit staging pathname."""

        source_path = Path(source)
        destination_path = Path(destination)
        if source_path.parent != destination_path.parent:
            raise ValueError("source and destination must share a parent directory")

        with source_path.open("wb") as sink:
            sink.write(payload)
            FaultingFileSync(sink, self._file_sync_spec).sync()

        self._replace.replace(source_path, destination_path)
        self._directory_sync.sync(destination_path.parent)
