from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .feedback_fuzz import FeedbackCampaignResult, run_feedback_guided_campaign
from .fuzz import FuzzFailure
from .harness import DifferentialHarness
from .sqlite_two_connection_feedback import SQLiteTwoConnectionFeedbackEvaluator
from .sqlite_two_connection_fuzz import SQLiteTwoConnectionScenarioMutations
from .sqlite_two_connection_triage import (
    SQLiteTwoConnectionReducedFailureRepro,
    reduce_sqlite_two_connection_failure_to_repro,
)


@dataclass(frozen=True, slots=True)
class SQLiteTwoConnectionDiscoveryRepro:
    """One feedback-discovered two-connection failure reduced to replayable evidence."""

    campaign: FeedbackCampaignResult[bytes, str]
    triage: SQLiteTwoConnectionReducedFailureRepro

    @property
    def failure(self) -> FuzzFailure[bytes]:
        return self.triage.failure

    @property
    def reduced(self) -> bytes:
        return self.triage.reduced


def discover_sqlite_two_connection_failure_to_repro(
    seeds: Sequence[bytes],
    *,
    harness: DifferentialHarness,
    destination: Path,
    mutations_per_case: int = 8,
    max_evaluations: int = 1_000,
    max_corpus_entries: int = 256,
    max_feature_visits_per_evaluation: int = 4_096,
    max_case_bytes: int = 65_536,
    max_candidate_visits_per_mutation: int = 1_024,
    max_evaluations_per_phase: int = 1_000,
    max_candidate_visits_per_phase: int = 10_000,
    metadata: dict[str, Any] | None = None,
) -> SQLiteTwoConnectionDiscoveryRepro:
    """Discover the first stable scenario failure, reduce it, and publish a repro.

    This is a target-specific composition boundary above the generic feedback campaign,
    differential harness, reducer, and repro primitives. Each admitted corpus entry uses
    the deterministic two-connection mutation schedule; construction of that schedule is
    independently bounded before any candidate is returned. The feedback campaign stops
    at its first retained stable failure. If no failure is discovered within the supplied
    campaign limits, the function fails closed before creating repro evidence.

    The discovered FuzzFailure is passed unchanged into the existing structured
    two-connection triage path. Reduction therefore preserves the exact captured stable
    signature across step deletion, setup deletion, and scalar-parameter simplification,
    and write_repro revalidates the minimized case before publication.
    """

    def mutate(case: bytes, mutation_index: int) -> bytes:
        mutations = SQLiteTwoConnectionScenarioMutations(
            (case,),
            max_case_bytes=max_case_bytes,
            max_seeds=1,
            max_candidate_visits=max_candidate_visits_per_mutation,
        )
        generated = mutations.case_count - 1
        if generated <= 0:
            return case
        return mutations(1 + (mutation_index % generated))

    campaign = run_feedback_guided_campaign(
        seeds=seeds,
        mutate=mutate,
        evaluate=SQLiteTwoConnectionFeedbackEvaluator(harness),
        mutations_per_case=mutations_per_case,
        max_evaluations=max_evaluations,
        max_corpus_entries=max_corpus_entries,
        max_unique_failures=1,
        max_feature_visits_per_evaluation=max_feature_visits_per_evaluation,
    )
    if not campaign.failures:
        raise ValueError("feedback campaign discovered no stable failure")

    triage = reduce_sqlite_two_connection_failure_to_repro(
        campaign.failures[0],
        harness=harness,
        destination=destination,
        max_evaluations_per_phase=max_evaluations_per_phase,
        max_candidate_visits_per_phase=max_candidate_visits_per_phase,
        metadata=metadata,
    )
    return SQLiteTwoConnectionDiscoveryRepro(campaign=campaign, triage=triage)
