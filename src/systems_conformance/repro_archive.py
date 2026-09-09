import io
import os
import shutil
import stat
import tempfile
import zipfile
from pathlib import Path

from .directory_sync_fault import FaultingDirectorySync
from .fault import FaultSpec
from .fsync_fault import FaultingFileSync
from .repro import (
    DEFAULT_MAX_REPRO_INPUT_BYTES,
    DEFAULT_MAX_REPRO_MANIFEST_BYTES,
    ReproBundle,
    load_repro_bundle,
)

REPRO_ARCHIVE_MEMBERS = ("input.bin", "manifest.json")
DEFAULT_MAX_REPRO_ARCHIVE_BYTES = (
    DEFAULT_MAX_REPRO_INPUT_BYTES + DEFAULT_MAX_REPRO_MANIFEST_BYTES + 4096
)
_FIXED_ZIP_TIMESTAMP = (1980, 1, 1, 0, 0, 0)


def _regular_zip_info(name: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, date_time=_FIXED_ZIP_TIMESTAMP)
    info.compress_type = zipfile.ZIP_STORED
    info.create_system = 3
    info.external_attr = 0o100644 << 16
    return info


def _has_explicit_non_regular_unix_type(member: zipfile.ZipInfo) -> bool:
    if member.create_system != 3:
        return False
    mode = member.external_attr >> 16
    file_type = stat.S_IFMT(mode)
    return file_type not in {0, stat.S_IFREG}


def _read_bounded_bytes(path: Path, *, max_bytes: int, label: str) -> bytes:
    with path.open("rb") as source:
        data = source.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise ValueError(f"{label} exceeds configured byte limit")
    return data


def _publish_file_no_replace(staging_path: Path, destination: Path) -> None:
    """Atomically publish one closed staging file without replacing a destination."""

    try:
        os.link(staging_path, destination)
    except FileExistsError:
        raise FileExistsError(
            f"repro archive destination already exists: {destination}"
        ) from None


def _non_triggering_fault_spec(operation: str) -> FaultSpec:
    """Return a valid spec that cannot trigger at this one-shot sync boundary."""

    return FaultSpec(operation=operation, occurrence=1, kind="io_error")


def _export_repro_archive(
    bundle_path: Path,
    archive_path: Path,
    *,
    max_input_bytes: int,
    max_manifest_bytes: int,
    durable: bool,
    file_sync_spec: FaultSpec | None,
    directory_sync_spec: FaultSpec | None,
) -> Path:
    bundle_path = Path(bundle_path)
    archive_path = Path(archive_path)
    if archive_path.exists() or archive_path.is_symlink():
        raise FileExistsError(f"repro archive destination already exists: {archive_path}")

    directory_sync = None
    effective_file_sync_spec = None
    if durable:
        effective_file_sync_spec = file_sync_spec or _non_triggering_fault_spec("fsync")
        directory_sync = FaultingDirectorySync(
            directory_sync_spec or _non_triggering_fault_spec("dir_fsync")
        )
    elif file_sync_spec is not None or directory_sync_spec is not None:
        raise ValueError("fault specs require durable repro archive export")

    loaded = load_repro_bundle(
        bundle_path,
        max_input_bytes=max_input_bytes,
        max_manifest_bytes=max_manifest_bytes,
    )
    manifest = _read_bounded_bytes(
        bundle_path / "manifest.json",
        max_bytes=max_manifest_bytes,
        label="repro manifest",
    )

    archive_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix=f".{archive_path.name}.snapshot-",
        dir=archive_path.parent,
    ) as snapshot_dir:
        snapshot = Path(snapshot_dir)
        (snapshot / "input.bin").write_bytes(loaded.input_bytes)
        (snapshot / "manifest.json").write_bytes(manifest)
        load_repro_bundle(
            snapshot,
            max_input_bytes=max_input_bytes,
            max_manifest_bytes=max_manifest_bytes,
        )
        input_bytes = (snapshot / "input.bin").read_bytes()
        manifest = (snapshot / "manifest.json").read_bytes()

        staging_fd, staging_name = tempfile.mkstemp(
            prefix=f".{archive_path.name}.export-",
            suffix=".tmp",
            dir=archive_path.parent,
        )
        os.close(staging_fd)
        staging_archive = Path(staging_name)
        try:
            with zipfile.ZipFile(
                staging_archive,
                mode="w",
                compression=zipfile.ZIP_STORED,
                allowZip64=False,
            ) as archive:
                archive.writestr(_regular_zip_info("input.bin"), input_bytes)
                archive.writestr(_regular_zip_info("manifest.json"), manifest)

            if durable:
                assert effective_file_sync_spec is not None
                with staging_archive.open("r+b") as sink:
                    FaultingFileSync(sink, effective_file_sync_spec).sync()

            _publish_file_no_replace(staging_archive, archive_path)

            if directory_sync is not None:
                directory_sync.sync(archive_path.parent)
        finally:
            if staging_archive.exists():
                staging_archive.unlink()

    return archive_path


def export_repro_archive(
    bundle_path: Path,
    archive_path: Path,
    *,
    max_input_bytes: int = DEFAULT_MAX_REPRO_INPUT_BYTES,
    max_manifest_bytes: int = DEFAULT_MAX_REPRO_MANIFEST_BYTES,
) -> Path:
    """Export one validated repro bundle as a deterministic portable ZIP.

    The archive contains exactly one bounded snapshot of ``input.bin`` and
    ``manifest.json`` that has been validated together. ZIP_STORED plus fixed
    member metadata keeps equal bundles byte-for-byte reproducible across export
    locations while avoiding decompression bombs on the supported import path.
    The final archive path is published atomically only after the ZIP is closed,
    so readers never observe a partially written transport artifact.
    """

    return _export_repro_archive(
        bundle_path,
        archive_path,
        max_input_bytes=max_input_bytes,
        max_manifest_bytes=max_manifest_bytes,
        durable=False,
        file_sync_spec=None,
        directory_sync_spec=None,
    )


def export_durable_repro_archive(
    bundle_path: Path,
    archive_path: Path,
    *,
    file_sync_spec: FaultSpec | None = None,
    directory_sync_spec: FaultSpec | None = None,
    max_input_bytes: int = DEFAULT_MAX_REPRO_INPUT_BYTES,
    max_manifest_bytes: int = DEFAULT_MAX_REPRO_MANIFEST_BYTES,
) -> Path:
    """Export and durably publish a repro archive with deterministic sync faults.

    The closed staging ZIP is first flushed through a real file ``fsync``, then
    hard-linked into place without clobbering an existing destination, and finally
    followed by a real containing-directory ``fsync``. Optional fault specs inject
    deterministic ``EIO`` at either sync boundary. Directory fsync is not portable
    on Windows, so this API fails closed there before publishing a destination.
    """

    return _export_repro_archive(
        bundle_path,
        archive_path,
        max_input_bytes=max_input_bytes,
        max_manifest_bytes=max_manifest_bytes,
        durable=True,
        file_sync_spec=file_sync_spec,
        directory_sync_spec=directory_sync_spec,
    )


def import_repro_archive(
    archive_path: Path,
    destination: Path,
    *,
    max_input_bytes: int = DEFAULT_MAX_REPRO_INPUT_BYTES,
    max_manifest_bytes: int = DEFAULT_MAX_REPRO_MANIFEST_BYTES,
    max_archive_bytes: int = DEFAULT_MAX_REPRO_ARCHIVE_BYTES,
) -> ReproBundle:
    """Import a deterministic repro archive through the normal bundle validator.

    Only the two direct-child regular members emitted by
    :func:`export_repro_archive` are accepted. The source archive is first read
    into one bounded immutable byte snapshot, so later path mutation cannot
    change the ZIP bytes being validated. Unexpected paths, duplicates,
    encryption, compression-method drift, oversized artifacts, and invalid
    bundle contents are rejected before the destination becomes visible.
    Existing destination entries, including dangling symlinks, are never
    intentionally replaced.
    """

    if max_archive_bytes <= 0:
        raise ValueError("max_archive_bytes must be positive")

    archive_path = Path(archive_path)
    destination = Path(destination)
    if archive_path.is_symlink() or not archive_path.is_file():
        raise ValueError(f"repro archive must be a regular file: {archive_path}")
    archive_bytes = _read_bounded_bytes(
        archive_path,
        max_bytes=max_archive_bytes,
        label="repro archive",
    )
    if destination.exists() or destination.is_symlink():
        raise FileExistsError(f"repro bundle destination already exists: {destination}")

    with zipfile.ZipFile(io.BytesIO(archive_bytes), mode="r") as archive:
        members = archive.infolist()
        names = [member.filename for member in members]
        if len(members) != len(REPRO_ARCHIVE_MEMBERS) or set(names) != set(
            REPRO_ARCHIVE_MEMBERS
        ):
            raise ValueError("repro archive must contain exactly input.bin and manifest.json")
        if len(names) != len(set(names)):
            raise ValueError("repro archive contains duplicate members")

        by_name = {member.filename: member for member in members}
        for member in members:
            if member.is_dir() or _has_explicit_non_regular_unix_type(member):
                raise ValueError("repro archive members must be regular files")
            if member.flag_bits & 0x1:
                raise ValueError("encrypted repro archive members are not supported")
            if member.compress_type != zipfile.ZIP_STORED:
                raise ValueError("repro archive members must use ZIP_STORED")

        if by_name["input.bin"].file_size > max_input_bytes:
            raise ValueError("repro input exceeds max_input_bytes")
        if by_name["manifest.json"].file_size > max_manifest_bytes:
            raise ValueError("repro manifest exceeds max_manifest_bytes")

        input_bytes = archive.read("input.bin")
        manifest_bytes = archive.read("manifest.json")

    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(
        tempfile.mkdtemp(
            prefix=f".{destination.name}.import-",
            dir=destination.parent,
        )
    )
    published = False
    try:
        (staging / "input.bin").write_bytes(input_bytes)
        (staging / "manifest.json").write_bytes(manifest_bytes)
        load_repro_bundle(
            staging,
            max_input_bytes=max_input_bytes,
            max_manifest_bytes=max_manifest_bytes,
        )
        if destination.exists() or destination.is_symlink():
            raise FileExistsError(
                f"repro bundle destination already exists: {destination}"
            )
        os.rename(staging, destination)
        published = True
    finally:
        if not published and staging.exists():
            shutil.rmtree(staging)

    return ReproBundle(
        path=destination,
        manifest_path=destination / "manifest.json",
        input_path=destination / "input.bin",
    )