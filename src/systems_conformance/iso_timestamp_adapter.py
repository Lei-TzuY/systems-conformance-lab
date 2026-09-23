from __future__ import annotations

import platform
import sys
from dataclasses import dataclass, field

from .harness import CommandTarget


def _python_runtime_identity() -> tuple[str, str]:
    return (
        sys.implementation.name,
        platform.python_version(),
    )


@dataclass(frozen=True, slots=True)
class ISOTimestampTarget:
    """Python datetime ISO timestamp parsing target over raw stdin bytes.

    The semantic surface is deliberately limited to timestamps carrying an explicit
    UTC marker or numeric offset. Accepted values are normalized to UTC epoch
    milliseconds and a millisecond-resolution UTC ISO string. Native parser acceptance
    policy is otherwise preserved.
    """

    _runtime_identity: tuple[str, str] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "_runtime_identity", _python_runtime_identity())

    @property
    def runtime_identity(self) -> tuple[str, str]:
        """Return Python implementation and version captured at construction."""
        return self._runtime_identity

    def as_command_target(self) -> CommandTarget:
        implementation, python_version = self._runtime_identity
        return CommandTarget(
            (
                sys.executable,
                "-m",
                "systems_conformance._iso_timestamp_worker",
                "--python-implementation",
                implementation,
                "--python-version",
                python_version,
            )
        )
