from collections.abc import Callable
from dataclasses import dataclass
from typing import Generic, Literal, TypeVar

from .comparator import ComparisonResult

CaseT = TypeVar("CaseT")
FuzzClassification = Literal["match", "product_mismatch", "infrastructure_failure"]


@dataclass(frozen=True, slots=True)
class FuzzCampaignResult(Generic[CaseT]):
    """Outcome of one deterministic, bounded fuzz campaign."""

    evaluations: int
    classification: FuzzClassification
    failing_case: CaseT | None
    comparison: ComparisonResult | None
    exhausted_budget: bool


def run_fuzz_campaign(
    *,
    cases: Callable[[int], CaseT],
    evaluate: Callable[[CaseT], ComparisonResult],
    max_evaluations: int = 1_000,
) -> FuzzCampaignResult[CaseT]:
    """Evaluate deterministic cases until failure or budget exhaustion.

    The case source receives a monotonically increasing zero-based index rather
    than shared mutable randomness. This keeps scheduling deterministic while
    allowing adapters to derive seeded or corpus-based cases however they need.

    Product mismatches and infrastructure failures are terminal but remain
    explicitly distinct. Exceptions from case generation or evaluation are not
    swallowed: a broken harness must not be converted into a product result.
    """

    if max_evaluations <= 0:
        raise ValueError("max_evaluations must be positive")

    for index in range(max_evaluations):
        case = cases(index)
        comparison = evaluate(case)
        _validate_comparison(comparison)

        if comparison.classification == "match":
            continue

        return FuzzCampaignResult(
            evaluations=index + 1,
            classification=comparison.classification,
            failing_case=case,
            comparison=comparison,
            exhausted_budget=False,
        )

    return FuzzCampaignResult(
        evaluations=max_evaluations,
        classification="match",
        failing_case=None,
        comparison=None,
        exhausted_budget=True,
    )


def _validate_comparison(comparison: ComparisonResult) -> None:
    is_match = comparison.classification == "match"
    if comparison.equivalent != is_match:
        raise ValueError("inconsistent comparison result")
    if is_match and comparison.mismatches:
        raise ValueError("inconsistent comparison result")
    if not is_match and not comparison.mismatches:
        raise ValueError("inconsistent comparison result")
