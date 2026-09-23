from __future__ import annotations

import platform
import sys
from dataclasses import dataclass, field

from .harness import CommandTarget


def _python_runtime_identity() -> tuple[str, str]:
    return sys.implementation.name, platform.python_version()


@dataclass(frozen=True, slots=True)
class URLResolutionTarget:
    """Python urllib relative-reference resolution target.

    stdin uses a language-neutral binary frame: four big-endian bytes containing the
    base URL byte length, followed by the base UTF-8 bytes and then the reference UTF-8
    bytes. The base must be an absolute HTTP/HTTPS URL with a hostname. Resolution uses
    urllib.parse.urljoin and the result is projected onto the same bounded canonical
    record as URLParseTarget.

    Python implementation/version are captured in argv and verified before stdin is
    consumed so replay identity cannot silently cross a parser-runtime upgrade.
    """

    _runtime_identity: tuple[str, str] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "_runtime_identity", _python_runtime_identity())

    @property
    def runtime_identity(self) -> tuple[str, str]:
        return self._runtime_identity

    def as_command_target(self) -> CommandTarget:
        implementation, python_version = self._runtime_identity
        return CommandTarget(
            (
                sys.executable,
                "-m",
                "systems_conformance._url_resolution_worker",
                "--python-implementation",
                implementation,
                "--python-version",
                python_version,
            )
        )
