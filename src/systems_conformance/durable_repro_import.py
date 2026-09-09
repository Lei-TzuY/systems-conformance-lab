from __future__ import annotations

import errno
import shutil
import tempfile
from pathlib import Path

from .directory_publish import publish_directory_no_replace
from .directory_sync_fault import FaultingDirectorySync
from .fault import FaultController, FaultSpec
from .fsync_fault import FaultingFileSync
from .repro import (
    DEFAULT_MAX_REPRO_INPUT_BYTES,
    DEFAULT_MAX_REPRO_MANIFEST_BYTES,
    ReproBundle,
)
from .repro_archive import DEFAULT_MAX_REPRO_ARCHIVE_BYTES, import_repro_archive

_IMPORT_SYNC_OPERATION = "import_sync"
_IMPORT_SYNC_STAGES = 4


def _non_triggering_spec(operation: str) -> FaultSpec:
    return FaultSpec(operation=operation, occurrence=1, kind="io_error")


def _checkpoint(controller: FaultController) -> None:
    fault = controller.checkpoint(_IMPORT_SYNC_OPERATION)
    if fault is not None:
        raise OSError(errno.EIO, "injected durable repro import sync fault")


def _sync_file(path: Path) -> None:
    with path.open("r+b") as sink:
        FaultingFileSync(sink, _non_triggering_spec("fsync")).sync()


def _sync_directory(path: Path) -> None:
    FaultingDirectorySync(_non_triggering_spec("dir_fsync")).sync(path)


def import_durable_repro_archive(
    archive_path: Path,
    destination: Path,
    *,
    sync_fault_spec: FaultSpec | None = None,
    max_input_bytes: int = DEFAULT_MAX_REPRO_INPUT_BYTES,
    max_manifest_bytes: int = DEFAULT_MAX_REPRO_MANIFEST_BYTES,
    max_archive_bytes: int = DEFAULT_MAX_REPRO_ARCHIVE_BYTES,
) -> ReproBundle:
    """Import, validate, and durably publish one repro bundle.

    The archive first traverses the ordinary bounded importer into a private
    staging bundle. The validated ``input.bin`` and ``manifest.json`` are then
    fsynced, followed by the staging bundle directory. Only after those durable
    preconditions succeed is the complete directory published with an atomic
    no-replace primitive and its containing directory fsynced.

    ``sync_fault_spec`` may use ``operation='import_sync'`` and ``kind='io_error'``
    to inject deterministic EIO at occurrence 0 (input fsync), 1 (manifest fsync),
    2 (staging-directory fsync), or 3 (post-publication parent-directory fsync).
    Failures at occurrences 0-2 leave no destination. Occurrence 3 reports the
    truthful post-publication state: the destination is visible, but publication
    durability has not been established. Directory fsync is not portable on
    Windows, so this API fails closed there before staging or publication.
    """

    destination = Path(destination)
    if destination.exists() or destination.is_symlink():
        raise FileExistsError(f"repro bundle destination already exists: {destination}")

    # Constructor validation intentionally happens before any staging work so
    # unsupported platforms fail closed without making a destination visible.
    FaultingDirectorySync(_non_triggering_spec("dir_fsync"))

    if sync_fault_spec is not None:
        if sync_fault_spec.operation != _IMPORT_SYNC_OPERATION:
            raise ValueError("durable repro import faults require operation='import_sync'")
        if sync_fault_spec.kind != "io_error":
            raise ValueError(
                f"unsupported durable repro import fault kind: {sync_fault_spec.kind}"
            )
        controller = FaultController(sync_fault_spec)
    else:
        controller = FaultController(
            FaultSpec(_IMPORT_SYNC_OPERATION, _IMPORT_SYNC_STAGES, "io_error")
        )

    destination.parent.mkdir(parents=True, exist_ok=True)
    holder = Path(
        tempfile.mkdtemp(
            prefix=f".{destination.name}.durable-import-",
            dir=destination.parent,
        )
    )
    staged = holder / "bundle"
    published = False
    try:
        import_repro_archive(
            archive_path,
            staged,
            max_input_bytes=max_input_bytes,
            max_manifest_bytes=max_manifest_bytes,
            max_archive_bytes=max_archive_bytes,
        )

        _checkpoint(controller)
        _sync_file(staged / "input.bin")
        _checkpoint(controller)
        _sync_file(staged / "manifest.json")
        _checkpoint(controller)
        _sync_directory(staged)

        publish_directory_no_replace(staged, destination)
        published = True

        _checkpoint(controller)
        _sync_directory(destination.parent)
    finally:
        if holder.exists():
            shutil.rmtree(holder)

    if not published:
        raise RuntimeError("durable repro import did not publish a destination")

    return ReproBundle(
        path=destination,
        manifest_path=destination / "manifest.json",
        input_path=destination / "input.bin",
    )
