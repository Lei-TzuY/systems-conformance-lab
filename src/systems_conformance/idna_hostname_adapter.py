from __future__ import annotations

import platform
import sys
import unicodedata
from dataclasses import dataclass, field

from .harness import CommandTarget


def _python_runtime_identity() -> tuple[str, str, str]:
    return (
        sys.implementation.name,
        platform.python_version(),
        unicodedata.ucd_3_2_0.unidata_version,
    )


@dataclass(frozen=True, slots=True)
class IDNAHostnameTarget:
    """Python stdlib IDNA2003 hostname-to-ASCII target over strict UTF-8 stdin.

    The target exposes Python's native encodings.idna / Nameprep policy rather than
    normalizing it toward WHATWG behavior. Python implementation/version plus the fixed
    Unicode 3.2 Nameprep table identity are bound into argv and verified before stdin is
    semantically processed.
    """

    _runtime_identity: tuple[str, str, str] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "_runtime_identity", _python_runtime_identity())

    @property
    def runtime_identity(self) -> tuple[str, str, str]:
        """Return implementation, Python version, and IDNA Unicode table version."""
        return self._runtime_identity

    def as_command_target(self) -> CommandTarget:
        implementation, python_version, idna_unicode_version = self._runtime_identity
        return CommandTarget(
            (
                sys.executable,
                "-m",
                "systems_conformance._idna_hostname_worker",
                "--python-implementation",
                implementation,
                "--python-version",
                python_version,
                "--idna-unicode-version",
                idna_unicode_version,
            )
        )
