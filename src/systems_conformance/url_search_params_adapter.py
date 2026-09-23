from __future__ import annotations

import platform
import sys
from dataclasses import dataclass, field

from .harness import CommandTarget

DEFAULT_MAX_INITIAL_PAIRS = 256
DEFAULT_MAX_OPERATIONS = 256
DEFAULT_MAX_FIELD_BYTES = 8192


def _python_runtime_identity() -> tuple[str, str]:
    return sys.implementation.name, platform.python_version()


def _validate_positive_integer(name: str, value: object) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{name} must be a positive integer")


@dataclass(frozen=True, slots=True)
class URLSearchParamsTarget:
    """Python ordered-query mutation target.

    The binary request contains an ordered initial pair list followed by ordered
    append/set/delete/sort operations. Python deliberately uses its native Unicode
    string ordering for sort and urllib.parse.urlencode for serialization rather than
    emulating WHATWG policy.

    Structural ceilings and captured Python runtime identity are immutable process
    configuration and therefore participate in replay identity.
    """

    max_initial_pairs: int = DEFAULT_MAX_INITIAL_PAIRS
    max_operations: int = DEFAULT_MAX_OPERATIONS
    max_field_bytes: int = DEFAULT_MAX_FIELD_BYTES
    _runtime_identity: tuple[str, str] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        _validate_positive_integer("max_initial_pairs", self.max_initial_pairs)
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
                "systems_conformance._url_search_params_worker",
                "--max-initial-pairs",
                str(self.max_initial_pairs),
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
