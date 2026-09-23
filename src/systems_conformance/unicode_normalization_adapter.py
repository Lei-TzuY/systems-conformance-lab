from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import Literal

from .harness import CommandTarget

_NORMALIZATION_FORMS = frozenset({"NFC", "NFD", "NFKC", "NFKD"})


@dataclass(frozen=True, slots=True)
class UnicodeNormalizationTarget:
    """Python Unicode normalization target over strict UTF-8 stdin.

    Raw case bytes are decoded with strict UTF-8 before normalization. Successful text
    and decode rejection are canonicalized to a deterministic JSON surface so the
    generic differential harness compares normalization semantics rather than runtime
    exception details.

    The normalization form is process configuration and therefore participates in the
    target argv and replay identity.
    """

    form: Literal["NFC", "NFD", "NFKC", "NFKD"] = "NFC"

    def __post_init__(self) -> None:
        if self.form not in _NORMALIZATION_FORMS:
            raise ValueError("form must be 'NFC', 'NFD', 'NFKC', or 'NFKD'")

    def as_command_target(self) -> CommandTarget:
        """Return the immutable Python normalization process target."""

        return CommandTarget(
            (
                sys.executable,
                "-m",
                "systems_conformance._unicode_normalization_worker",
                "--form",
                self.form,
            )
        )
