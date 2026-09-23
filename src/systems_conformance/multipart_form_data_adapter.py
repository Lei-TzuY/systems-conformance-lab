from __future__ import annotations

import platform
import sys
from dataclasses import dataclass, field

from .harness import CommandTarget

DEFAULT_MAX_MULTIPART_BODY_BYTES = 64 * 1024
MAX_CONFIGURED_MULTIPART_BODY_BYTES = 256 * 1024
MULTIPART_FORM_DATA_BOUNDARY = "systems-conformance-boundary"


def _python_runtime_identity() -> tuple[str, str]:
    return sys.implementation.name, platform.python_version()


def _validate_max_body_bytes(value: object) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError("max_body_bytes must be an integer")
    if value < 0 or value > MAX_CONFIGURED_MULTIPART_BODY_BYTES:
        raise ValueError(
            "max_body_bytes must be between 0 and "
            f"{MAX_CONFIGURED_MULTIPART_BODY_BYTES}"
        )


@dataclass(frozen=True, slots=True)
class MultipartFormDataTarget:
    """Python email-based multipart/form-data parser over bounded raw body bytes."""

    max_body_bytes: int = DEFAULT_MAX_MULTIPART_BODY_BYTES
    _runtime_identity: tuple[str, str] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        _validate_max_body_bytes(self.max_body_bytes)
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
                "systems_conformance._multipart_form_data_worker",
                "--python-implementation",
                implementation,
                "--python-version",
                python_version,
                "--max-body-bytes",
                str(self.max_body_bytes),
            )
        )
