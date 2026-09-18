from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .repro import LoadedReproBundle, load_repro_bundle

_FAILURE_MODEL = "failure_model"
_REMOUNT_PERFORMED = "remount_performed"
_POWER_LOSS_RECOVERY_PROVEN = "power_loss_recovery_proven"
_EVIDENCE_FIELDS = frozenset(
    {_FAILURE_MODEL, _REMOUNT_PERFORMED, _POWER_LOSS_RECOVERY_PROVEN}
)

REDUCTION_EVIDENCE_METADATA_KEY = "systems_conformance_reduction"
REDUCTION_EVIDENCE_SCHEMA_VERSION = "systems-conformance.reduction-evidence.v1"
_REDUCTION_EVIDENCE_FIELDS = frozenset(
    {
        "schema_version",
        "evaluations",
        "candidate_visits",
        "accepted_steps",
        "exhausted_budget",
        "termination_reason",
    }
)


@dataclass(frozen=True, slots=True)
class FailureModelEvidence:
    """Validated machine-readable boundary for one fault/recovery claim."""

    failure_model: str
    remount_performed: bool
    power_loss_recovery_proven: bool


@dataclass(frozen=True, slots=True)
class ReductionEvidence:
    """Validated deterministic reducer work accounting loaded from a repro."""

    evaluations: int
    candidate_visits: int
    accepted_steps: int
    exhausted_budget: bool
    termination_reason: str
    schema_version: str = REDUCTION_EVIDENCE_SCHEMA_VERSION


def validate_failure_model_evidence(metadata: dict[str, Any]) -> FailureModelEvidence | None:
    """Validate optional failure-model evidence without upgrading partial claims.

    Legacy metadata without any evidence fields remains valid. Once one evidence
    field is present, all three fields are required so archive/replay consumers
    cannot silently lose the boundary that qualifies a durability claim.
    """

    present = _EVIDENCE_FIELDS.intersection(metadata)
    if not present:
        return None
    missing = sorted(_EVIDENCE_FIELDS - present)
    if missing:
        raise ValueError(f"incomplete failure-model evidence: missing={missing!r}")

    failure_model = metadata[_FAILURE_MODEL]
    remount_performed = metadata[_REMOUNT_PERFORMED]
    power_loss_recovery_proven = metadata[_POWER_LOSS_RECOVERY_PROVEN]
    if not isinstance(failure_model, str) or not failure_model:
        raise TypeError("failure_model must be a non-empty string")
    if not isinstance(remount_performed, bool):
        raise TypeError("remount_performed must be a boolean")
    if not isinstance(power_loss_recovery_proven, bool):
        raise TypeError("power_loss_recovery_proven must be a boolean")

    if failure_model == "process-kill-same-mount":
        if remount_performed:
            raise ValueError("process-kill-same-mount evidence cannot claim a remount")
        if power_loss_recovery_proven:
            raise ValueError(
                "process-kill-same-mount evidence cannot claim power-loss recovery"
            )

    return FailureModelEvidence(
        failure_model=failure_model,
        remount_performed=remount_performed,
        power_loss_recovery_proven=power_loss_recovery_proven,
    )


def validate_reduction_evidence(metadata: dict[str, Any]) -> ReductionEvidence | None:
    """Validate optional package-owned reducer evidence and its semantic invariants."""

    value = metadata.get(REDUCTION_EVIDENCE_METADATA_KEY)
    if value is None:
        return None
    if not isinstance(value, dict):
        raise TypeError("reduction evidence must be an object")

    fields = frozenset(value)
    unexpected = sorted(fields - _REDUCTION_EVIDENCE_FIELDS)
    missing = sorted(_REDUCTION_EVIDENCE_FIELDS - fields)
    if unexpected or missing:
        details = []
        if unexpected:
            details.append(f"unexpected={unexpected!r}")
        if missing:
            details.append(f"missing={missing!r}")
        raise ValueError(f"reduction evidence fields do not match v1 schema: {', '.join(details)}")
    if value.get("schema_version") != REDUCTION_EVIDENCE_SCHEMA_VERSION:
        raise ValueError("unsupported reduction evidence schema")

    counters: dict[str, int] = {}
    for field in ("evaluations", "candidate_visits", "accepted_steps"):
        counter = value.get(field)
        if not isinstance(counter, int) or isinstance(counter, bool):
            raise TypeError(f"reduction evidence {field} must be an integer")
        if counter < 0:
            raise ValueError(f"reduction evidence {field} must be non-negative")
        counters[field] = counter

    if counters["evaluations"] < 1:
        raise ValueError("reduction evidence evaluations must include the initial evaluation")
    if counters["accepted_steps"] > counters["evaluations"] - 1:
        raise ValueError("reduction evidence accepted_steps exceeds evaluated candidates")
    if counters["accepted_steps"] > counters["candidate_visits"]:
        raise ValueError("reduction evidence accepted_steps exceeds candidate visits")

    exhausted_budget = value.get("exhausted_budget")
    if not isinstance(exhausted_budget, bool):
        raise TypeError("reduction evidence exhausted_budget must be a boolean")
    termination_reason = value.get("termination_reason")
    if termination_reason not in {"fixed_point", "evaluation_budget"}:
        raise ValueError("invalid reduction evidence termination_reason")
    expected_reason = "evaluation_budget" if exhausted_budget else "fixed_point"
    if termination_reason != expected_reason:
        raise ValueError("reduction evidence termination_reason contradicts exhausted_budget")

    return ReductionEvidence(
        evaluations=counters["evaluations"],
        candidate_visits=counters["candidate_visits"],
        accepted_steps=counters["accepted_steps"],
        exhausted_budget=exhausted_budget,
        termination_reason=termination_reason,
    )


def load_evidenced_repro_bundle(path: Path, **kwargs: Any) -> LoadedReproBundle:
    """Load a canonical repro bundle and fail closed on evidence-contract drift."""

    bundle = load_repro_bundle(path, **kwargs)
    validate_failure_model_evidence(bundle.metadata)
    validate_reduction_evidence(bundle.metadata)
    return bundle
