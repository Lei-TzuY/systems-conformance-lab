from collections.abc import Callable, Hashable, Iterable, Sequence
from dataclasses import dataclass
from typing import Generic, TypeVar

from .comparator import ComparisonResult

CaseT = TypeVar("CaseT")
FeatureT = TypeVar("FeatureT", bound=Hashable)


@dataclass(frozen=True, slots=True)
class FeedbackCorpusEntry(Generic[CaseT, FeatureT]):
    case: CaseT
    new_features: frozenset[FeatureT]


@dataclass(frozen=True, slots=True)
class FeedbackCampaignResult(Generic[CaseT, FeatureT]):
    evaluations: int
    corpus: tuple[FeedbackCorpusEntry[CaseT, FeatureT], ...]
    features: frozenset[FeatureT]
    exhausted_budget: bool
    reached_corpus_limit: bool


def run_feedback_guided_campaign(
    *,
    seeds: Sequence[CaseT],
    mutate: Callable[[CaseT, int], CaseT],
    evaluate: Callable[[CaseT], tuple[ComparisonResult, Iterable[FeatureT]]],
    mutations_per_case: int = 8,
    max_evaluations: int = 1_000,
    max_corpus_entries: int = 256,
) -> FeedbackCampaignResult[CaseT, FeatureT]:
    """Grow a deterministic corpus from newly observed feedback features.

    Seeds are evaluated in order. Each admitted entry is then visited in FIFO
    order and receives exactly ``mutations_per_case`` indexed mutations. A case
    is admitted only when it contributes at least one previously unseen feature.
    This makes the queue replayable without shared randomness while bounding
    target executions and corpus growth.
    """

    if not seeds:
        raise ValueError("seeds must not be empty")
    if mutations_per_case <= 0:
        raise ValueError("mutations_per_case must be positive")
    if max_evaluations <= 0:
        raise ValueError("max_evaluations must be positive")
    if max_corpus_entries <= 0:
        raise ValueError("max_corpus_entries must be positive")

    corpus: list[FeedbackCorpusEntry[CaseT, FeatureT]] = []
    seen_features: set[FeatureT] = set()
    evaluations = 0

    def consider(case: CaseT) -> bool:
        nonlocal evaluations
        comparison, raw_features = evaluate(case)
        _validate_comparison(comparison)
        evaluations += 1
        features = frozenset(raw_features)
        new_features = features.difference(seen_features)
        if not new_features:
            return False
        seen_features.update(new_features)
        corpus.append(FeedbackCorpusEntry(case=case, new_features=frozenset(new_features)))
        return len(corpus) >= max_corpus_entries

    for seed in seeds:
        if evaluations >= max_evaluations:
            break
        if consider(seed):
            return _result(evaluations, corpus, seen_features, False, True)

    parent_index = 0
    while parent_index < len(corpus) and evaluations < max_evaluations:
        parent = corpus[parent_index].case
        parent_index += 1
        for mutation_index in range(mutations_per_case):
            if evaluations >= max_evaluations:
                break
            if consider(mutate(parent, mutation_index)):
                return _result(evaluations, corpus, seen_features, False, True)

    return _result(
        evaluations,
        corpus,
        seen_features,
        evaluations >= max_evaluations,
        False,
    )


def _result(
    evaluations: int,
    corpus: list[FeedbackCorpusEntry[CaseT, FeatureT]],
    features: set[FeatureT],
    exhausted_budget: bool,
    reached_corpus_limit: bool,
) -> FeedbackCampaignResult[CaseT, FeatureT]:
    return FeedbackCampaignResult(
        evaluations=evaluations,
        corpus=tuple(corpus),
        features=frozenset(features),
        exhausted_budget=exhausted_budget,
        reached_corpus_limit=reached_corpus_limit,
    )


def _validate_comparison(comparison: ComparisonResult) -> None:
    is_match = comparison.classification == "match"
    if comparison.equivalent != is_match:
        raise ValueError("inconsistent comparison result")
    if is_match and comparison.mismatches:
        raise ValueError("inconsistent comparison result")
    if not is_match and not comparison.mismatches:
        raise ValueError("inconsistent comparison result")
