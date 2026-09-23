from __future__ import annotations

import platform
import sys
from dataclasses import dataclass, field

from .harness import CommandTarget


def _python_runtime_identity() -> tuple[str, str]:
    return sys.implementation.name, platform.python_version()


@dataclass(frozen=True, slots=True)
class URLQueryCanonicalizationTarget:
    """Python full-URL query parse/re-encode/serialize interoperability target.

    Raw stdin is one strict UTF-8 absolute HTTP(S) URL. The worker validates the URL,
    decodes its query as ordered application/x-www-form-urlencoded pairs with strict
    percent-decoded UTF-8, re-encodes those pairs through urllib.parse.urlencode, and
    serializes the full URL with the canonicalized query.

    Python implementation/version are captured in argv and verified before stdin is
    consumed so replay identity cannot silently cross a runtime policy change.
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
                "systems_conformance._url_query_canonicalization_worker",
                "--python-implementation",
                implementation,
                "--python-version",
                python_version,
            )
        )
