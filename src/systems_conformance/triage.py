from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .failure import failure_signature
from .fuzz import FuzzFailure
from .harness import DifferentialHarness
from .reducer import ReductionResult, reduce_case
from .repro import ReproBundle

REDUCTION_EVIDENCE_METADATA_KEY = "systems_conformance_reduction"
REDUCTION_EVIDENCE_SCHEMA_VERSION = "systems-conformance.reduction-evidence.v1"


@dataclass(frozen=True, slots=True)
class ReducedFailureRepro:
    """One fuzz witness reduced and published under its original stable identity."""

    failure: FuzzFailure[bytes]
    reduction: ReductionResult[bytes]
    repro: ReproBundle


def _reduction_evidence(reduction: ReductionResult[bytes]) -> dict[str, Any]:
    """Return JSON-safe deterministic work evidence without embedding case bytes."""
    return {
        "schema_version": REDUCTION_EVIDENCE_SCHEMA_VERSION,
        "evaluations": reduction.evaluations,
        "candidate_visits": reduction.candidate_visits,
        "accepted_steps": reduction.accepted_steps,
        "exhausted_budget": reduction.exhausted_budget,
        "termination_reason": reduction.termination_reason,
    }


def reduce_failure_to_repro(
    failure: FuzzFailure[bytes],
    *,
    harness: DifferentialHarness,
    destination: Path,
    candidates: Callable[[bytes], Iterable[bytes]],
    measure: Callable[[bytes], int] = len,
    max_evaluations: int = 1_000,
    metadata: dict[str, Any] | None = None,
) -> ReducedFailureRepro:
    """Revalidate, reduce, and publish one captured fuzz failure deterministically.

    The captured comparison is checked against its declared stable signature before
    any target executes. Reduction then uses the live harness as the preservation
    predicate, so infrastructure and product failures cannot silently cross classes.
    Repro publication performs one final signature check before writing evidence.
    Deterministic reducer work accounting is persisted under a reserved metadata key
    so replay and offline triage can distinguish a fixed point from a budget-bounded
    intermediate result without retaining the in-memory ``ReductionResult``.
    """

    captured_signature = failure_signature(failure.comparison)
    if captured_signature is None or captured_signature != failure.signature:
        raise ValueError("fuzz failure carries an inconsistent stable signature")
    if metadata is not None and REDUCTION_EVIDENCE_METADATA_KEY in metadata:
        raise ValueError(
            f"metadata key {REDUCTION_EVIDENCE_METADATA_KEY!r} is reserved for reducer evidence"
        )

    reduction = reduce_case(
        failure.case,
        candidates=candidates,
        preserves_failure=lambda case: harness.preserves_failure(case, failure.signature),
        measure=measure,
        max_evaluations=max_evaluations,
    )
    repro_metadata = dict(metadata or {})
    repro_metadata[REDUCTION_EVIDENCE_METADATA_KEY] = _reduction_evidence(reduction)
    repro = harness.write_repro(
        destination,
        input_bytes=reduction.reduced,
        expected_signature=failure.signature,
        metadata=repro_metadata,
    )
    return ReducedFailureRepro(failure=failure, reduction=reduction, repro=repro)
