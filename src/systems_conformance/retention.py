import shutil
from dataclasses import dataclass
from pathlib import Path

from .repro import load_repro_bundle


@dataclass(frozen=True, slots=True)
class RetentionResult:
    """Summary of one deterministic repro-bundle retention pass."""

    kept: tuple[Path, ...]
    removed: tuple[Path, ...]
    ignored: tuple[Path, ...]


def enforce_repro_retention(root: Path, *, max_bundles: int) -> RetentionResult:
    """Keep at most ``max_bundles`` fully validated repro bundles below ``root``.

    Only direct child directories that pass the canonical bounded repro loader
    are eligible for deletion. Symlinks, malformed/tampered bundles, unknown
    schema versions, and any bundle replay would reject are ignored. Eligible
    bundles are ordered newest first by manifest mtime, with directory name as
    a deterministic tiebreaker.
    """

    if isinstance(max_bundles, bool) or not isinstance(max_bundles, int):
        raise TypeError("max_bundles must be an int")
    if max_bundles < 0:
        raise ValueError("max_bundles must be non-negative")

    root = Path(root)
    if not root.exists():
        return RetentionResult(kept=(), removed=(), ignored=())
    if not root.is_dir():
        raise NotADirectoryError(root)

    eligible: list[tuple[int, str, Path]] = []
    ignored: list[Path] = []

    for child in sorted(root.iterdir(), key=lambda path: path.name):
        if child.is_symlink() or not child.is_dir():
            ignored.append(child)
            continue

        try:
            bundle = load_repro_bundle(child)
            manifest_mtime_ns = bundle.path.joinpath("manifest.json").stat().st_mtime_ns
        except (OSError, UnicodeError, TypeError, ValueError):
            ignored.append(child)
            continue

        eligible.append((manifest_mtime_ns, child.name, child))

    eligible.sort(key=lambda item: (-item[0], item[1]))
    kept = [item[2] for item in eligible[:max_bundles]]
    removed = [item[2] for item in eligible[max_bundles:]]

    for path in removed:
        shutil.rmtree(path)

    return RetentionResult(
        kept=tuple(kept),
        removed=tuple(removed),
        ignored=tuple(ignored),
    )
