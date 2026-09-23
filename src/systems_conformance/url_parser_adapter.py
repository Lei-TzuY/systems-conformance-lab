from __future__ import annotations

import platform
import sys
from dataclasses import dataclass, field

from .harness import CommandTarget


def _python_runtime_identity() -> tuple[str, str]:
    return sys.implementation.name, platform.python_version()


@dataclass(frozen=True, slots=True)
class URLParseTarget:
    """Python urllib.parse target for absolute HTTP/HTTPS URL semantics.

    Raw stdin bytes are strict UTF-8. Successful parses are projected onto a bounded
    canonical field set while decode and parse rejection use stable JSON errors.

    The Python implementation/version are captured at construction, carried in argv,
    and verified by the worker before stdin is consumed so replay identity cannot
    silently cross a parser-runtime upgrade.
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
                "systems_conformance._url_parse_worker",
                "--python-implementation",
                implementation,
                "--python-version",
                python_version,
            )
        )
