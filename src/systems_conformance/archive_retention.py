from __future__ import annotations

import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path

from .repro import DEFAULT_MAX_REPRO_INPUT_BYTES, DEFAULT_MAX_REPRO_MANIFEST_BYTES
from .repro_archive import DEFAULT_MAX_REPRO_ARCHIVE_BYTES, import_repro_archive


@dataclass(frozen=True, slots=True)
class ArchiveRetentionResult:
    """Summary of one bounded portable-repro archive retention pass."""

    kept: tuple[Path, ...]
    removed: tuple[Path, ...]
    ignored: tuple[Path, ...]


def enforce_repro_archive_retention(
    root: Path,
    *,
    max_archives: int,
    max_total_archive_bytes: int | None = None,
    max_input_bytes: int = DEFAULT_MAX_REPRO_INPUT_BYTES,
    max_manifest_bytes: int = DEFAULT_MAX_REPRO_MANIFEST_BYTES,
    max_archive_bytes: int = DEFAULT_MAX_REPRO_ARCHIVE_BYTES,
) -> ArchiveRetentionResult:
    """Retain validated direct-child repro archives within count and byte budgets.

    Eligibility uses the canonical bounded archive importer, including bundle schema
    and digest validation. Directories, symlinks, malformed archives, and unrelated
    files are ignored rather than deleted. Eligible archives are ordered newest first
    by mtime with filename as a deterministic tiebreaker. The optional aggregate byte
    budget is applied greedily in that order, so an archive that does not fit is
    removed while later smaller archives may still be retained. Deletion uses
    ``unlink`` so a path swapped to a symlink after validation is removed as a link,
    never followed.
    """

    if isinstance(max_archives, bool) or not isinstance(max_archives, int):
        raise TypeError("max_archives must be an int")
    if max_archives < 0:
        raise ValueError("max_archives must be non-negative")
    if max_total_archive_bytes is not None:
        if isinstance(max_total_archive_bytes, bool) or not isinstance(
            max_total_archive_bytes, int
        ):
            raise TypeError("max_total_archive_bytes must be an int or None")
        if max_total_archive_bytes < 0:
            raise ValueError("max_total_archive_bytes must be non-negative")

    root = Path(root)
    if not root.exists():
        return ArchiveRetentionResult(kept=(), removed=(), ignored=())
    if not root.is_dir():
        raise NotADirectoryError(root)

    eligible: list[tuple[int, str, Path, int]] = []
    ignored: list[Path] = []

    with tempfile.TemporaryDirectory(prefix="systems-conformance-archive-retention-") as temp:
        scratch = Path(temp)
        for index, child in enumerate(sorted(root.iterdir(), key=lambda path: path.name)):
            if child.is_symlink() or not child.is_file():
                ignored.append(child)
                continue
            try:
                stat_result = child.stat()
                import_repro_archive(
                    child,
                    scratch / f"bundle-{index}",
                    max_input_bytes=max_input_bytes,
                    max_manifest_bytes=max_manifest_bytes,
                    max_archive_bytes=max_archive_bytes,
                )
            except (OSError, UnicodeError, TypeError, ValueError, zipfile.BadZipFile):
                ignored.append(child)
                continue
            eligible.append(
                (stat_result.st_mtime_ns, child.name, child, stat_result.st_size)
            )

    eligible.sort(key=lambda item: (-item[0], item[1]))
    kept: list[Path] = []
    removed: list[Path] = []
    kept_bytes = 0

    for _, _, path, archive_size in eligible:
        count_fits = len(kept) < max_archives
        bytes_fit = (
            max_total_archive_bytes is None
            or kept_bytes + archive_size <= max_total_archive_bytes
        )
        if count_fits and bytes_fit:
            kept.append(path)
            kept_bytes += archive_size
        else:
            removed.append(path)

    for path in removed:
        try:
            path.unlink()
        except FileNotFoundError:
            pass

    return ArchiveRetentionResult(
        kept=tuple(kept),
        removed=tuple(removed),
        ignored=tuple(ignored),
    )
