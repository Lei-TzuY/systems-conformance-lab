from __future__ import annotations

import platform
import sys
from dataclasses import dataclass, field

from .harness import CommandTarget

DEFAULT_MAX_DATA_URL_BYTES = 64 * 1024
MAX_CONFIGURED_DATA_URL_BYTES = 1024 * 1024


def _python_runtime_identity() -> tuple[str, str]:
    return (
        sys.implementation.name,
        platform.python_version(),
    )


def _validate_max_data_url_bytes(value: object) -> None:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value <= 0
        or value > MAX_CONFIGURED_DATA_URL_BYTES
    ):
        raise ValueError(
            "max_data_url_bytes must be an integer between 1 and "
            f"{MAX_CONFIGURED_DATA_URL_BYTES}"
        )


@dataclass(frozen=True, slots=True)
class DataURLFetchTarget:
    """Python urllib data-URL fetch target with a hard input ceiling.

    Only ASCII data URLs are admitted. A strict scheme gate runs before urllib so fuzz
    cases cannot escape into network or file access. The byte ceiling and captured Python
    runtime identity are immutable process configuration and replay identity.
    """

    max_data_url_bytes: int = DEFAULT_MAX_DATA_URL_BYTES
    _runtime_identity: tuple[str, str] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        _validate_max_data_url_bytes(self.max_data_url_bytes)
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
                "systems_conformance._data_url_fetch_worker",
                "--max-data-url-bytes",
                str(self.max_data_url_bytes),
                "--python-implementation",
                implementation,
                "--python-version",
                python_version,
            )
        )
