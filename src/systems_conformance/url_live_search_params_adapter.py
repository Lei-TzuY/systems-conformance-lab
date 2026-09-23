from __future__ import annotations

import platform
import sys
from dataclasses import dataclass, field

from .harness import CommandTarget

DEFAULT_MAX_URL_BYTES = 16 * 1024
DEFAULT_MAX_OPERATIONS = 64
DEFAULT_MAX_FIELD_BYTES = 4096


def _python_runtime_identity() -> tuple[str, str]:
    return sys.implementation.name, platform.python_version()


def _validate_positive_integer(name: str, value: object) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{name} must be a positive integer")


@dataclass(frozen=True, slots=True)
class URLLiveSearchParamsTarget:
    """Python composed URL/search-params coupling model.

    Python does not expose a native WHATWG URL object with a live URLSearchParams view.
    This target therefore composes urllib.parse URL state with an ordered pair model and
    native urllib.parse form encoding. Params mutations write the serialized query back
    into the URL, while direct search replacement reparses into the existing logical
    params view.

    Structural ceilings and captured Python runtime identity are immutable process
    configuration and therefore participate in replay identity.
    """

    max_url_bytes: int = DEFAULT_MAX_URL_BYTES
    max_operations: int = DEFAULT_MAX_OPERATIONS
    max_field_bytes: int = DEFAULT_MAX_FIELD_BYTES
    _runtime_identity: tuple[str, str] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        _validate_positive_integer("max_url_bytes", self.max_url_bytes)
        _validate_positive_integer("max_operations", self.max_operations)
        _validate_positive_integer("max_field_bytes", self.max_field_bytes)
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
                "systems_conformance._url_live_search_params_worker",
                "--max-url-bytes",
                str(self.max_url_bytes),
                "--max-operations",
                str(self.max_operations),
                "--max-field-bytes",
                str(self.max_field_bytes),
                "--python-implementation",
                implementation,
                "--python-version",
                python_version,
            )
        )
