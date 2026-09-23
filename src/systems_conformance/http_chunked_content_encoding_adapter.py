from __future__ import annotations

import platform
import sys
from dataclasses import dataclass, field

from .harness import CommandTarget

DEFAULT_MAX_TRANSFER_BODY_BYTES = 64 * 1024
DEFAULT_MAX_OBSERVED_BODY_BYTES = 64 * 1024
MAX_CONFIGURED_BODY_BYTES = 1024 * 1024


def _python_runtime_identity() -> tuple[str, str]:
    return sys.implementation.name, platform.python_version()


def _validate_budget(name: str, value: object) -> None:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value <= 0
        or value > MAX_CONFIGURED_BODY_BYTES
    ):
        raise ValueError(
            f"{name} must be an integer between 1 and {MAX_CONFIGURED_BODY_BYTES}"
        )


@dataclass(frozen=True, slots=True)
class HTTPChunkedContentEncodingTarget:
    """Python urllib target for chunked plus Content-Encoding response semantics."""

    max_transfer_body_bytes: int = DEFAULT_MAX_TRANSFER_BODY_BYTES
    max_observed_body_bytes: int = DEFAULT_MAX_OBSERVED_BODY_BYTES
    _runtime_identity: tuple[str, str] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        _validate_budget("max_transfer_body_bytes", self.max_transfer_body_bytes)
        _validate_budget("max_observed_body_bytes", self.max_observed_body_bytes)
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
                "systems_conformance._http_chunked_content_encoding_worker",
                "--max-transfer-body-bytes",
                str(self.max_transfer_body_bytes),
                "--max-observed-body-bytes",
                str(self.max_observed_body_bytes),
                "--python-implementation",
                implementation,
                "--python-version",
                python_version,
            )
        )
