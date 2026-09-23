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
class Base64CodecTarget:
    """Python stdlib Base64/Base64url encode/decode target over raw stdin bytes.

    Encode mode accepts arbitrary bytes. Decode mode accepts ASCII transport text and
    preserves Python's native padding and alphabet acceptance policy rather than
    normalizing toward another runtime. Mode, alphabet, and the captured Python runtime
    identity are immutable process configuration and participate in replay identity.
    """

    mode: Literal["encode", "decode"] = "encode"
    alphabet: Literal["base64", "base64url"] = "base64"
    _runtime_identity: tuple[str, str] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        if self.mode not in {"encode", "decode"}:
            raise ValueError("mode must be 'encode' or 'decode'")
        if self.alphabet not in {"base64", "base64url"}:
            raise ValueError("alphabet must be 'base64' or 'base64url'")
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
                "systems_conformance._base64_codec_worker",
                "--mode",
                self.mode,
                "--alphabet",
                self.alphabet,
                "--python-implementation",
                implementation,
                "--python-version",
                python_version,
            )
        )
