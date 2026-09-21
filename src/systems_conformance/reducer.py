from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Generic, Literal, TypeVar

CaseT = TypeVar("CaseT")


@dataclass(frozen=True, slots=True)
class ReductionResult(Generic[CaseT]):
    """Outcome of one deterministic greedy reduction run."""

    original: CaseT
    reduced: CaseT
    evaluations: int
    candidate_visits: int
    accepted_steps: int
    exhausted_budget: bool
    termination_reason: Literal["fixed_point", "evaluation_budget"] = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "termination_reason",
            "evaluation_budget" if self.exhausted_budget else "fixed_point",
        )


class CandidateBudgetExhausted(RuntimeError):
    """Infrastructure failure raised when reducer candidate enumeration is exhausted."""

    def __init__(self, *, candidate_visits: int, max_candidate_visits: int) -> None:
        self.candidate_visits = candidate_visits
        self.max_candidate_visits = max_candidate_visits
        super().__init__(
            "reducer candidate enumeration budget exhausted "
            f"after {candidate_visits} visits (limit {max_candidate_visits})"
        )


def reduce_case(
    initial: CaseT,
    *,
    candidates: Callable[[CaseT], Iterable[CaseT]],
    preserves_failure: Callable[[CaseT], bool],
    measure: Callable[[CaseT], int],
    max_evaluations: int = 1_000,
    max_candidate_visits: int = 10_000,
) -> ReductionResult[CaseT]:
    """Greedily reduce a failing case while preserving its failure class.

    Candidate order is significant and therefore defines deterministic
    first-improvement behavior. A candidate is only evaluated when its measure
    is strictly smaller than the current case, which prevents cycles and makes
    progress explicit. Candidate enumeration has its own global visit budget so
    an adapter cannot evade ``max_evaluations`` by yielding an unbounded stream
    of non-progressing candidates. The structural budget is checked before both
    invoking the untrusted candidate factory and requesting the next item from
    its iterator, so adapter work beyond the configured ceiling cannot execute.
    Successful results expose the total number of visited candidates, including
    candidates skipped without evaluation, plus a machine-readable termination
    reason distinguishing a fixed point from evaluation-budget exhaustion, so
    callers can persist deterministic reducer work evidence. Exhausting the
    structural budget raises ``CandidateBudgetExhausted`` with the same work
    evidence rather than being mistaken for product-level non-reproduction. The
    initial case must reproduce the target failure. Predicate exceptions are
    intentionally not swallowed so harness failures cannot be mistaken for
    product-level non-reproduction.
    """

    if max_evaluations <= 0:
        raise ValueError("max_evaluations must be positive")
    if max_candidate_visits <= 0:
        raise ValueError("max_candidate_visits must be positive")

    initial_measure = measure(initial)
    if initial_measure < 0:
        raise ValueError("measure must be non-negative")

    evaluations = 1
    if not preserves_failure(initial):
        raise ValueError("initial case does not preserve the target failure")

    current = initial
    current_measure = initial_measure
    accepted_steps = 0
    candidate_visits = 0

    while evaluations < max_evaluations:
        if candidate_visits >= max_candidate_visits:
            raise CandidateBudgetExhausted(
                candidate_visits=candidate_visits,
                max_candidate_visits=max_candidate_visits,
            )
        accepted = False
        candidate_iterator = iter(candidates(current))
        while True:
            if candidate_visits >= max_candidate_visits:
                raise CandidateBudgetExhausted(
                    candidate_visits=candidate_visits,
                    max_candidate_visits=max_candidate_visits,
                )
            try:
                candidate = next(candidate_iterator)
            except StopIteration:
                break
            candidate_visits += 1

            candidate_measure = measure(candidate)
            if candidate_measure < 0:
                raise ValueError("measure must be non-negative")
            if candidate_measure >= current_measure:
                continue
            if evaluations >= max_evaluations:
                return ReductionResult(
                    original=initial,
                    reduced=current,
                    evaluations=evaluations,
                    candidate_visits=candidate_visits,
                    accepted_steps=accepted_steps,
                    exhausted_budget=True,
                )

            evaluations += 1
            if preserves_failure(candidate):
                current = candidate
                current_measure = candidate_measure
                accepted_steps += 1
                accepted = True
                break

        if not accepted:
            return ReductionResult(
                original=initial,
                reduced=current,
                evaluations=evaluations,
                candidate_visits=candidate_visits,
                accepted_steps=accepted_steps,
                exhausted_budget=False,
            )

    return ReductionResult(
        original=initial,
        reduced=current,
        evaluations=evaluations,
        candidate_visits=candidate_visits,
        accepted_steps=accepted_steps,
        exhausted_budget=True,
    )
