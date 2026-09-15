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


@dataclass(frozen=True, slots=True)
class FailureModelEvidence:
    """Validated machine-readable boundary for one fault/recovery claim."""

    failure_model: str
    remount_performed: bool
    power_loss_recovery_proven: bool


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


def load_evidenced_repro_bundle(path: Path, **kwargs: Any) -> LoadedReproBundle:
    """Load a canonical repro bundle and fail closed on evidence-contract drift."""

    bundle = load_repro_bundle(path, **kwargs)
    validate_failure_model_evidence(bundle.metadata)
    return bundle
