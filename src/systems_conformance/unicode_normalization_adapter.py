from __future__ import annotations

import platform
import sys
import unicodedata
from dataclasses import dataclass, field
from typing import Literal

from .harness import CommandTarget

_NORMALIZATION_FORMS = frozenset({"NFC", "NFD", "NFKC", "NFKD"})


def _python_runtime_identity() -> tuple[str, str, str]:
    return (
        sys.implementation.name,
        platform.python_version(),
        unicodedata.unidata_version,
    )


@dataclass(frozen=True, slots=True)
class UnicodeNormalizationTarget:
    """Python Unicode normalization target over strict UTF-8 stdin.

    Raw case bytes are decoded with strict UTF-8 before normalization. Successful text
    and decode rejection are canonicalized to a deterministic JSON surface so the
    generic differential harness compares normalization semantics rather than runtime
    exception details.

    The normalization form and captured Python/Unicode semantic runtime identity are
    process configuration and therefore participate in target argv and replay identity.
    The worker verifies that identity before consuming case bytes, so an adapter created
    under one Unicode table cannot silently execute under another.
    """

    form: Literal["NFC", "NFD", "NFKC", "NFKD"] = "NFC"
    _runtime_identity: tuple[str, str, str] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        if self.form not in _NORMALIZATION_FORMS:
            raise ValueError("form must be 'NFC', 'NFD', 'NFKC', or 'NFKD'")
        object.__setattr__(self, "_runtime_identity", _python_runtime_identity())

    @property
    def runtime_identity(self) -> tuple[str, str, str]:
        """Return implementation, Python version, and Unicode data version."""
        return self._runtime_identity

    def as_command_target(self) -> CommandTarget:
        """Return the immutable Python normalization process target."""

        implementation, python_version, unicode_version = self._runtime_identity
        return CommandTarget(
            (
                sys.executable,
                "-m",
                "systems_conformance._unicode_normalization_worker",
                "--form",
                self.form,
                "--python-implementation",
                implementation,
                "--python-version",
                python_version,
                "--unicode-version",
                unicode_version,
            )
        )
