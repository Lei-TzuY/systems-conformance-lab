from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .failure import failure_signature
from .fuzz import FuzzFailure
from .harness import DifferentialHarness
from .reducer import ReductionResult, reduce_case
from .repro import ReproBundle
from .sqlite_two_connection_reducer import (
    sqlite_two_connection_parameter_complexity,
    sqlite_two_connection_parameter_reductions,
    sqlite_two_connection_setup_count,
    sqlite_two_connection_setup_deletions,
    sqlite_two_connection_step_count,
    sqlite_two_connection_step_deletions,
)


@dataclass(frozen=True, slots=True)
class SQLiteTwoConnectionReducedFailureRepro:
    """One two-connection SQLite failure reduced through structured phases."""

    failure: FuzzFailure[bytes]
    step_reduction: ReductionResult[bytes]
    setup_reduction: ReductionResult[bytes]
    parameter_reduction: ReductionResult[bytes]
    repro: ReproBundle

    @property
    def reduced(self) -> bytes:
        return self.parameter_reduction.reduced


def reduce_sqlite_two_connection_failure_to_repro(
    failure: FuzzFailure[bytes],
    *,
    harness: DifferentialHarness,
    destination: Path,
    max_evaluations_per_phase: int = 1_000,
    max_candidate_visits_per_phase: int = 10_000,
    metadata: dict[str, Any] | None = None,
) -> SQLiteTwoConnectionReducedFailureRepro:
    """Reduce and publish one two-connection SQLite mismatch deterministically.

    Ordered scenario steps are reduced first because they define the concurrency
    behavior under test. Setup statements are deleted after the surviving
    interleaving stabilizes, followed by scalar simplification across retained
    step parameters. Every candidate is re-executed through the live differential
    harness and must preserve the exact captured stable failure signature.

    Evaluation and candidate-enumeration work are independently bounded per phase.
    The final case is executed once more by write_repro under the expected
    signature before any evidence is published.
    """

    captured_signature = failure_signature(failure.comparison)
    if captured_signature is None or captured_signature != failure.signature:
        raise ValueError("fuzz failure carries an inconsistent stable signature")

    def preserves(case: bytes) -> bool:
        return harness.preserves_failure(case, failure.signature)

    step_reduction = reduce_case(
        failure.case,
        candidates=sqlite_two_connection_step_deletions,
        preserves_failure=preserves,
        measure=sqlite_two_connection_step_count,
        max_evaluations=max_evaluations_per_phase,
        max_candidate_visits=max_candidate_visits_per_phase,
    )
    setup_reduction = reduce_case(
        step_reduction.reduced,
        candidates=sqlite_two_connection_setup_deletions,
        preserves_failure=preserves,
        measure=sqlite_two_connection_setup_count,
        max_evaluations=max_evaluations_per_phase,
        max_candidate_visits=max_candidate_visits_per_phase,
    )
    parameter_reduction = reduce_case(
        setup_reduction.reduced,
        candidates=sqlite_two_connection_parameter_reductions,
        preserves_failure=preserves,
        measure=sqlite_two_connection_parameter_complexity,
        max_evaluations=max_evaluations_per_phase,
        max_candidate_visits=max_candidate_visits_per_phase,
    )

    repro = harness.write_repro(
        destination,
        input_bytes=parameter_reduction.reduced,
        expected_signature=failure.signature,
        metadata=metadata,
    )
    return SQLiteTwoConnectionReducedFailureRepro(
        failure=failure,
        step_reduction=step_reduction,
        setup_reduction=setup_reduction,
        parameter_reduction=parameter_reduction,
        repro=repro,
    )
