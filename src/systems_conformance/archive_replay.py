from __future__ import annotations

import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .failure import FailureSignature
from .harness import DifferentialHarness, DifferentialRun
from .repro import DEFAULT_MAX_REPRO_INPUT_BYTES, DEFAULT_MAX_REPRO_MANIFEST_BYTES
from .repro_archive import DEFAULT_MAX_REPRO_ARCHIVE_BYTES, import_repro_archive


@dataclass(frozen=True, slots=True)
class ArchiveReproReplay:
    """Stable replay result for one validated portable repro archive.

    Archive replay imports into a private temporary bundle so callers do not need to
    publish transport artifacts into their retained repro directory. The returned
    evidence is copied out of that private bundle and therefore remains usable after
    temporary cleanup.
    """

    archive_path: Path
    input_bytes: bytes
    signature: FailureSignature
    metadata: dict[str, Any]
    replay_context_sha256: str | None
    run: DifferentialRun

    @property
    def reproduced(self) -> bool:
        """Return whether execution preserved the archive's stable failure identity."""
        return self.run.signature == self.signature


def replay_repro_archive(
    harness: DifferentialHarness,
    archive_path: Path,
    *,
    max_input_bytes: int = DEFAULT_MAX_REPRO_INPUT_BYTES,
    max_manifest_bytes: int = DEFAULT_MAX_REPRO_MANIFEST_BYTES,
    max_archive_bytes: int = DEFAULT_MAX_REPRO_ARCHIVE_BYTES,
    require_same_context: bool = True,
) -> ArchiveReproReplay:
    """Validate and replay a portable repro archive without persistent extraction.

    The archive first traverses the normal bounded, immutable-snapshot import path.
    The resulting private bundle then traverses ``DifferentialHarness.replay_repro``,
    including replay-context validation before untrusted input executes. The private
    import is removed on success and failure; only copied validated evidence is
    returned to the caller.
    """

    archive_path = Path(archive_path)
    with tempfile.TemporaryDirectory(prefix="systems-conformance-archive-replay-") as root:
        imported = import_repro_archive(
            archive_path,
            Path(root) / "bundle",
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
        return ArchiveReproReplay(
            archive_path=archive_path,
            input_bytes=replay.bundle.input_bytes,
            signature=replay.bundle.signature,
            metadata=dict(replay.bundle.metadata),
            replay_context_sha256=replay.bundle.replay_context_sha256,
            run=replay.run,
        )
