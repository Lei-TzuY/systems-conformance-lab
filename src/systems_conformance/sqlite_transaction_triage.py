from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .failure import failure_signature
from .fuzz import FuzzFailure
from .harness import DifferentialHarness
from .reducer import ReductionResult, reduce_case
from .repro import ReproBundle
from .sqlite_transaction_reducer import (
    sqlite_transaction_fault_occurrence_complexity,
    sqlite_transaction_fault_occurrence_reductions,
    sqlite_transaction_parameter_complexity,
    sqlite_transaction_parameter_reductions,
    sqlite_transaction_statement_count,
    sqlite_transaction_statement_deletions,
)


@dataclass(frozen=True, slots=True)
class SQLiteTransactionReducedFailureRepro:
    """One SQLite transaction failure reduced through all structured phases."""

    failure: FuzzFailure[bytes]
    statement_reduction: ReductionResult[bytes]
    parameter_reduction: ReductionResult[bytes]
    fault_reduction: ReductionResult[bytes]
    repro: ReproBundle

    @property
    def reduced(self) -> bytes:
        return self.fault_reduction.reduced


def reduce_sqlite_transaction_failure_to_repro(
    failure: FuzzFailure[bytes],
    *,
    harness: DifferentialHarness,
    destination: Path,
    max_evaluations_per_phase: int = 1_000,
    metadata: dict[str, Any] | None = None,
) -> SQLiteTransactionReducedFailureRepro:
    """Reduce one SQLite transaction witness across structured dimensions.

    Each phase independently revalidates the current case against the exact stable
    failure signature captured by the fuzz witness. Statement deletion runs first,
    followed by scalar-parameter simplification and fault-occurrence reduction.
    The final minimized input is re-executed once more by ``write_repro`` before
    evidence is published, so phase drift cannot silently produce a different
    product or infrastructure failure.
    """

    captured_signature = failure_signature(failure.comparison)
    if captured_signature is None or captured_signature != failure.signature:
        raise ValueError("fuzz failure carries an inconsistent stable signature")

    preserves = lambda case: harness.preserves_failure(case, failure.signature)

    statement_reduction = reduce_case(
        failure.case,
        candidates=sqlite_transaction_statement_deletions,
        preserves_failure=preserves,
        measure=sqlite_transaction_statement_count,
        max_evaluations=max_evaluations_per_phase,
    )
    parameter_reduction = reduce_case(
        statement_reduction.reduced,
        candidates=sqlite_transaction_parameter_reductions,
        preserves_failure=preserves,
        measure=sqlite_transaction_parameter_complexity,
        max_evaluations=max_evaluations_per_phase,
    )
    fault_reduction = reduce_case(
        parameter_reduction.reduced,
        candidates=sqlite_transaction_fault_occurrence_reductions,
        preserves_failure=preserves,
        measure=sqlite_transaction_fault_occurrence_complexity,
        max_evaluations=max_evaluations_per_phase,
    )

    repro = harness.write_repro(
        destination,
        input_bytes=fault_reduction.reduced,
        expected_signature=failure.signature,
        metadata=metadata,
    )
    return SQLiteTransactionReducedFailureRepro(
        failure=failure,
        statement_reduction=statement_reduction,
        parameter_reduction=parameter_reduction,
        fault_reduction=fault_reduction,
        repro=repro,
    )
