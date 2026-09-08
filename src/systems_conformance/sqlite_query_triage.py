from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .failure import failure_signature
from .fuzz import FuzzFailure
from .harness import DifferentialHarness
from .reducer import ReductionResult, reduce_case
from .repro import ReproBundle
from .sqlite_query_reducer import (
    sqlite_query_fault_occurrence_complexity,
    sqlite_query_fault_occurrence_reductions,
    sqlite_query_parameter_complexity,
    sqlite_query_parameter_reductions,
    sqlite_query_setup_statement_count,
    sqlite_query_setup_statement_deletions,
)


@dataclass(frozen=True, slots=True)
class SQLiteQueryReducedFailureRepro:
    """One SQLite query failure reduced through all structured phases."""

    failure: FuzzFailure[bytes]
    fault_reduction: ReductionResult[bytes]
    setup_reduction: ReductionResult[bytes]
    parameter_reduction: ReductionResult[bytes]
    repro: ReproBundle

    @property
    def reduced(self) -> bytes:
        return self.parameter_reduction.reduced


def reduce_sqlite_query_failure_to_repro(
    failure: FuzzFailure[bytes],
    *,
    harness: DifferentialHarness,
    destination: Path,
    max_evaluations_per_phase: int = 1_000,
    metadata: dict[str, Any] | None = None,
) -> SQLiteQueryReducedFailureRepro:
    """Reduce one SQLite query witness across structured dimensions.

    Each phase revalidates the current case against the exact stable failure
    signature captured by the fuzz witness. Fault occurrence is reduced first so
    an earlier setup checkpoint can unlock setup deletion; scalar query parameters
    are simplified after the setup shape stabilizes. The final minimized input is
    re-executed once more by ``write_repro`` before evidence is published.
    """

    captured_signature = failure_signature(failure.comparison)
    if captured_signature is None or captured_signature != failure.signature:
        raise ValueError("fuzz failure carries an inconsistent stable signature")

    def preserves(case: bytes) -> bool:
        return harness.preserves_failure(case, failure.signature)

    fault_reduction = reduce_case(
        failure.case,
        candidates=sqlite_query_fault_occurrence_reductions,
        preserves_failure=preserves,
        measure=sqlite_query_fault_occurrence_complexity,
        max_evaluations=max_evaluations_per_phase,
    )
    setup_reduction = reduce_case(
        fault_reduction.reduced,
        candidates=sqlite_query_setup_statement_deletions,
        preserves_failure=preserves,
        measure=sqlite_query_setup_statement_count,
        max_evaluations=max_evaluations_per_phase,
    )
    parameter_reduction = reduce_case(
        setup_reduction.reduced,
        candidates=sqlite_query_parameter_reductions,
        preserves_failure=preserves,
        measure=sqlite_query_parameter_complexity,
        max_evaluations=max_evaluations_per_phase,
    )

    repro = harness.write_repro(
        destination,
        input_bytes=parameter_reduction.reduced,
        expected_signature=failure.signature,
        metadata=metadata,
    )
    return SQLiteQueryReducedFailureRepro(
        failure=failure,
        fault_reduction=fault_reduction,
        setup_reduction=setup_reduction,
        parameter_reduction=parameter_reduction,
        repro=repro,
    )
