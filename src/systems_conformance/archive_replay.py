from __future__ import annotations

import hashlib
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .failure import FailureSignature
from .harness import DifferentialHarness, DifferentialRun
from .repro import DEFAULT_MAX_REPRO_INPUT_BYTES, DEFAULT_MAX_REPRO_MANIFEST_BYTES
from .repro_archive import (
    DEFAULT_MAX_REPRO_ARCHIVE_BYTES,
    _read_bounded_bytes,
    import_repro_archive,
)


@dataclass(frozen=True, slots=True)
class ArchiveReproReplay:
    """Stable replay result for one validated portable repro archive.

    Archive replay imports into a private temporary bundle so callers do not need to
    publish transport artifacts into their retained repro directory. The returned
    evidence is copied out of that private bundle and therefore remains usable after
    temporary cleanup.
    """

    archive_path: Path
    archive_sha256: str
    input_bytes: bytes
    signature: FailureSignature
    metadata: dict[str, Any]
    replay_context_sha256: str | None
    run: DifferentialRun

    @property
    def reproduced(self) -> bool:
        """Return whether execution preserved the archive's stable failure identity."""
        return self.run.signature == self.signature


def _validate_expected_archive_sha256(value: str | None) -> None:
    if value is None:
        return
    if not isinstance(value, str):
        raise TypeError("expected_archive_sha256 must be a string")
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError("expected_archive_sha256 must be a lowercase SHA-256 hex digest")


def replay_repro_archive(
    harness: DifferentialHarness,
    archive_path: Path,
    *,
    max_input_bytes: int = DEFAULT_MAX_REPRO_INPUT_BYTES,
    max_manifest_bytes: int = DEFAULT_MAX_REPRO_MANIFEST_BYTES,
    max_archive_bytes: int = DEFAULT_MAX_REPRO_ARCHIVE_BYTES,
    expected_archive_sha256: str | None = None,
    require_same_context: bool = True,
    require_reproduction: bool = False,
) -> ArchiveReproReplay:
    """Validate and replay a portable repro archive without persistent extraction.

    The source archive is read once into a bounded immutable byte snapshot. Its
    SHA-256 digest is captured as transport evidence and may be pinned by callers via
    ``expected_archive_sha256``. A digest mismatch fails before bundle import or
    untrusted target execution. The exact same snapshot then traverses the normal
    archive import path and ``DifferentialHarness.replay_repro``, including
    replay-context validation before untrusted input executes. The private import is
    removed on success and failure; only copied validated evidence is returned.

    When ``require_reproduction`` is true, a completed replay whose stable failure
    signature differs from the archived signature fails closed with ``RuntimeError``.
    This gate is intentionally separate from replay-context validation: callers may
    opt out of same-context enforcement for portability experiments while still
    requiring the transported witness to preserve its exact failure identity.
    """

    _validate_expected_archive_sha256(expected_archive_sha256)
    if max_archive_bytes <= 0:
        raise ValueError("max_archive_bytes must be positive")

    archive_path = Path(archive_path)
    if archive_path.is_symlink() or not archive_path.is_file():
        raise ValueError(f"repro archive must be a regular file: {archive_path}")
    archive_bytes = _read_bounded_bytes(
        archive_path,
        max_bytes=max_archive_bytes,
        label="repro archive",
    )
    archive_sha256 = hashlib.sha256(archive_bytes).hexdigest()
    if expected_archive_sha256 is not None and archive_sha256 != expected_archive_sha256:
        raise ValueError("repro archive sha256 does not match expected digest")

    with tempfile.TemporaryDirectory(prefix="systems-conformance-archive-replay-") as root:
        root_path = Path(root)
        snapshot_archive = root_path / "archive.zip"
        snapshot_archive.write_bytes(archive_bytes)
        imported = import_repro_archive(
            snapshot_archive,
            root_path / "bundle",
            max_input_bytes=max_input_bytes,
            max_manifest_bytes=max_manifest_bytes,
            max_archive_bytes=max_archive_bytes,
        )
        replay = harness.replay_repro(
            imported.path,
            max_input_bytes=max_input_bytes,
            max_manifest_bytes=max_manifest_bytes,
            require_same_context=require_same_context,
        )
        result = ArchiveReproReplay(
            archive_path=archive_path,
            archive_sha256=archive_sha256,
            input_bytes=replay.bundle.input_bytes,
            signature=replay.bundle.signature,
            metadata=dict(replay.bundle.metadata),
            replay_context_sha256=replay.bundle.replay_context_sha256,
            run=replay.run,
        )
        if require_reproduction and not result.reproduced:
            raise RuntimeError(
                "portable repro archive did not reproduce archived failure signature"
            )
        return result
