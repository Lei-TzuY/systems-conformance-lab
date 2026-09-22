from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .archive_replay import ArchiveReproReplay, replay_repro_archive
from .fuzz import FuzzFailure
from .harness import DifferentialHarness
from .repro_archive import export_repro_archive
from .sqlite_two_connection_discovery import (
    SQLiteTwoConnectionDiscoveryRepro,
    discover_sqlite_two_connection_failure_to_repro,
)


@dataclass(frozen=True, slots=True)
class SQLiteTwoConnectionArchiveEvidence:
    """One discovered SQLite failure packaged as replay-verified portable evidence."""

    discovery: SQLiteTwoConnectionDiscoveryRepro
    archive_path: Path
    replay: ArchiveReproReplay

    @property
    def failure(self) -> FuzzFailure[bytes]:
        return self.discovery.failure

    @property
    def reduced(self) -> bytes:
        return self.discovery.reduced

    @property
    def archive_sha256(self) -> str:
        return self.replay.archive_sha256


def discover_sqlite_two_connection_failure_to_archive(
    seeds: Sequence[bytes],
    *,
    harness: DifferentialHarness,
    repro_destination: Path,
    archive_path: Path,
    mutations_per_case: int = 8,
    max_evaluations: int = 1_000,
    max_corpus_entries: int = 256,
    max_feature_visits_per_evaluation: int = 4_096,
    max_case_bytes: int = 65_536,
    max_candidate_visits_per_mutation: int = 1_024,
    max_evaluations_per_phase: int = 1_000,
    max_candidate_visits_per_phase: int = 10_000,
    metadata: dict[str, Any] | None = None,
) -> SQLiteTwoConnectionArchiveEvidence:
    """Discover, minimize, archive, and replay-gate one SQLite failure.

    The archive destination is checked before expensive discovery begins: an already
    existing file, directory, or symlink fails closed without creating the repro
    destination. Discovery and structured reduction then run through the existing
    target-specific pipeline. The validated repro bundle is exported through the generic
    deterministic archive transport and replayed back from an immutable archive snapshot.

    The returned SHA-256 is the digest of the exact archive bytes that traversed archive
    import and replay. Callers may pin that digest in later replay_repro_archive handoffs
    to detect transport replacement before target execution. This function does not claim
    durable fsync publication; callers needing that guarantee should use the existing
    durable archive substrate as a separate storage policy.
    """

    archive_path = Path(archive_path)
    if archive_path.exists() or archive_path.is_symlink():
        raise FileExistsError(f"repro archive destination already exists: {archive_path}")

    discovery = discover_sqlite_two_connection_failure_to_repro(
        seeds,
        harness=harness,
        destination=Path(repro_destination),
        mutations_per_case=mutations_per_case,
        max_evaluations=max_evaluations,
        max_corpus_entries=max_corpus_entries,
        max_feature_visits_per_evaluation=max_feature_visits_per_evaluation,
        max_case_bytes=max_case_bytes,
        max_candidate_visits_per_mutation=max_candidate_visits_per_mutation,
        max_evaluations_per_phase=max_evaluations_per_phase,
        max_candidate_visits_per_phase=max_candidate_visits_per_phase,
        metadata=metadata,
    )
    archive = export_repro_archive(discovery.triage.repro.path, archive_path)
    replay = replay_repro_archive(
        harness,
        archive,
        require_same_context=True,
        require_reproduction=True,
    )
    return SQLiteTwoConnectionArchiveEvidence(
        discovery=discovery,
        archive_path=archive,
        replay=replay,
    )
