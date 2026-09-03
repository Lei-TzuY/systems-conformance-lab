import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .comparator import ComparisonResult
from .failure import FailureSignature
from .model import ExecutionResult

REPRO_BUNDLE_SCHEMA_VERSION = "systems-conformance.repro-bundle.v1"


@dataclass(frozen=True, slots=True)
class ReproBundle:
    """Description of one deterministic on-disk reproducer bundle."""

    path: Path
    manifest_path: Path
    input_path: Path
    schema_version: str = REPRO_BUNDLE_SCHEMA_VERSION


def write_repro_bundle(
    destination: Path,
    *,
    input_bytes: bytes,
    candidate: ExecutionResult,
    oracle: ExecutionResult,
    comparison: ComparisonResult,
    signature: FailureSignature,
    metadata: dict[str, Any] | None = None,
) -> ReproBundle:
    """Write a self-contained, deterministic reproducer bundle.

    Existing destinations are rejected so evidence cannot be silently
    overwritten. The manifest deliberately uses relative artifact names and
    sorted JSON keys, while the original input is retained byte-for-byte.
    """

    destination = Path(destination)
    if destination.exists():
        raise FileExistsError(f"repro bundle destination already exists: {destination}")
    if comparison.equivalent:
        raise ValueError("cannot create a repro bundle for a matching comparison")
    if metadata is not None and not isinstance(metadata, dict):
        raise TypeError("metadata must be a dict or None")

    destination.mkdir(parents=True)
    input_path = destination / "input.bin"
    manifest_path = destination / "manifest.json"

    try:
        input_path.write_bytes(input_bytes)
        manifest = {
            "schema_version": REPRO_BUNDLE_SCHEMA_VERSION,
            "input": {"path": input_path.name, "size_bytes": len(input_bytes)},
            "candidate": candidate.to_dict(),
            "oracle": oracle.to_dict(),
            "comparison": comparison.to_dict(),
            "failure_signature": signature.to_dict(),
            "metadata": {} if metadata is None else metadata,
        }
        manifest_path.write_text(
            json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
            encoding="utf-8",
            newline="\n",
        )
    except BaseException:
        # Avoid leaving a partially valid-looking bundle behind.
        if manifest_path.exists():
            manifest_path.unlink()
        if input_path.exists():
            input_path.unlink()
        try:
            destination.rmdir()
        except OSError:
            pass
        raise

    return ReproBundle(
        path=destination,
        manifest_path=manifest_path,
        input_path=input_path,
    )
