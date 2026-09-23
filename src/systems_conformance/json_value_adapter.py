from __future__ import annotations

import platform
import sys
from dataclasses import dataclass, field

from .harness import CommandTarget

DEFAULT_MAX_JSON_BYTES = 16 * 1024
DEFAULT_MAX_JSON_DEPTH = 64
DEFAULT_MAX_JSON_NODES = 4096


def _python_runtime_identity() -> tuple[str, str]:
    return sys.implementation.name, platform.python_version()


def _validate_positive_integer(name: str, value: object) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{name} must be a positive integer")


@dataclass(frozen=True, slots=True)
class JSONValueTarget:
    """Python native JSON value-semantics target.

    Raw stdin is strict UTF-8 JSON text. Successful parses are projected onto a
    language-neutral tagged value tree that preserves native numeric materialization
    while canonicalizing object-key observation order.
    """

    max_json_bytes: int = DEFAULT_MAX_JSON_BYTES
    max_depth: int = DEFAULT_MAX_JSON_DEPTH
    max_nodes: int = DEFAULT_MAX_JSON_NODES
    _runtime_identity: tuple[str, str] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        _validate_positive_integer("max_json_bytes", self.max_json_bytes)
        _validate_positive_integer("max_depth", self.max_depth)
        _validate_positive_integer("max_nodes", self.max_nodes)
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
                "systems_conformance._json_value_worker",
                "--max-json-bytes",
                str(self.max_json_bytes),
                "--max-depth",
                str(self.max_depth),
                "--max-nodes",
                str(self.max_nodes),
                "--python-implementation",
                implementation,
                "--python-version",
                python_version,
            )
        )
