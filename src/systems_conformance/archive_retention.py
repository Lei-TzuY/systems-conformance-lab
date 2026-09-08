from __future__ import annotations

import tempfile
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
    max_input_bytes: int = DEFAULT_MAX_REPRO_INPUT_BYTES,
    max_manifest_bytes: int = DEFAULT_MAX_REPRO_MANIFEST_BYTES,
    max_archive_bytes: int = DEFAULT_MAX_REPRO_ARCHIVE_BYTES,
) -> ArchiveRetentionResult:
    """Keep at most ``max_archives`` validated direct-child repro archives.

    Eligibility uses the canonical bounded archive importer, including bundle schema
    and digest validation. Directories, symlinks, malformed archives, and unrelated
    files are ignored rather than deleted. Eligible archives are ordered newest first
    by mtime with filename as a deterministic tiebreaker. Deletion uses ``unlink`` so
    a path swapped to a symlink after validation is removed as a link, never followed.
    """

    if isinstance(max_archives, bool) or not isinstance(max_archives, int):
        raise TypeError("max_archives must be an int")
    if max_archives < 0:
        raise ValueError("max_archives must be non-negative")

    root = Path(root)
    if not root.exists():
        return ArchiveRetentionResult(kept=(), removed=(), ignored=())
    if not root.is_dir():
        raise NotADirectoryError(root)

    eligible: list[tuple[int, str, Path]] = []
    ignored: list[Path] = []

    with tempfile.TemporaryDirectory(prefix="systems-conformance-archive-retention-") as temp:
        scratch = Path(temp)
        for index, child in enumerate(sorted(root.iterdir(), key=lambda path: path.name)):
            if child.is_symlink() or not child.is_file():
                ignored.append(child)
                continue
            try:
                mtime_ns = child.stat().st_mtime_ns
                import_repro_archive(
                    child,
                    scratch / f"bundle-{index}",
                    max_input_bytes=max_input_bytes,
                    max_manifest_bytes=max_manifest_bytes,
                    max_archive_bytes=max_archive_bytes,
                )
            except (OSError, UnicodeError, TypeError, ValueError):
                ignored.append(child)
                continue
            eligible.append((mtime_ns, child.name, child))

    eligible.sort(key=lambda item: (-item[0], item[1]))
    kept = [item[2] for item in eligible[:max_archives]]
    removed = [item[2] for item in eligible[max_archives:]]

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
