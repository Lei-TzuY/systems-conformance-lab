from __future__ import annotations

import platform
import sys
from dataclasses import dataclass, field

from .harness import CommandTarget

DEFAULT_MAX_JSON_DOCUMENT_BYTES = 64 * 1024
MAX_CONFIGURED_JSON_DOCUMENT_BYTES = 1024 * 1024


def _python_runtime_identity() -> tuple[str, str]:
    return (sys.implementation.name, platform.python_version())


@dataclass(frozen=True, slots=True)
class JSONParseTarget:
    """Python stdlib JSON parser target over bounded strict UTF-8 stdin."""

    max_document_bytes: int = DEFAULT_MAX_JSON_DOCUMENT_BYTES
    _runtime_identity: tuple[str, str] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        if isinstance(self.max_document_bytes, bool) or not isinstance(
            self.max_document_bytes, int
        ):
            raise TypeError("max_document_bytes must be an integer")
        if (
            self.max_document_bytes < 0
            or self.max_document_bytes > MAX_CONFIGURED_JSON_DOCUMENT_BYTES
        ):
            raise ValueError(
                "max_document_bytes must be between 0 and "
                f"{MAX_CONFIGURED_JSON_DOCUMENT_BYTES}"
            )
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
                "systems_conformance._json_parser_worker",
                "--python-implementation",
                implementation,
                "--python-version",
                python_version,
                "--max-document-bytes",
                str(self.max_document_bytes),
            )
        )
