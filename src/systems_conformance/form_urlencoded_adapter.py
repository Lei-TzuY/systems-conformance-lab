from __future__ import annotations

import platform
import sys
from dataclasses import dataclass, field
from typing import Literal

from .harness import CommandTarget


def _python_runtime_identity() -> tuple[str, str]:
    return (
        sys.implementation.name,
        platform.python_version(),
    )


@dataclass(frozen=True, slots=True)
class FormURLEncodedTarget:
    """Python application/x-www-form-urlencoded encode/decode target.

    Encode mode accepts a binary ordered-pair frame so repeated keys and ordering are
    preserved without involving a JSON parser. Decode mode accepts raw form body bytes
    and performs strict UTF-8 transport decoding before urllib.parse percent decoding.

    Mode plus the captured Python implementation/version are immutable process
    configuration and therefore participate in replay identity.
    """

    mode: Literal["encode", "decode"] = "encode"
    _runtime_identity: tuple[str, str] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        if self.mode not in {"encode", "decode"}:
            raise ValueError("mode must be 'encode' or 'decode'")
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
                "systems_conformance._form_urlencoded_worker",
                "--mode",
                self.mode,
                "--python-implementation",
                implementation,
                "--python-version",
                python_version,
            )
        )
