from __future__ import annotations

import platform
import sys
import zlib
from dataclasses import dataclass, field

from .harness import CommandTarget

DEFAULT_MAX_DECOMPRESSED_BYTES = 64 * 1024
MAX_CONFIGURED_DECOMPRESSED_BYTES = 16 * 1024 * 1024


def _python_runtime_identity() -> tuple[str, str, str]:
    return (
        sys.implementation.name,
        platform.python_version(),
        zlib.ZLIB_RUNTIME_VERSION,
    )


def _validate_max_decompressed_bytes(value: object) -> None:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value <= 0
        or value > MAX_CONFIGURED_DECOMPRESSED_BYTES
    ):
        raise ValueError(
            "max_decompressed_bytes must be an integer between 1 and "
            f"{MAX_CONFIGURED_DECOMPRESSED_BYTES}"
        )


@dataclass(frozen=True, slots=True)
class GzipDecompressionTarget:
    """Python gzip decompression target with a hard decoded-output ceiling.

    The worker uses the stdlib gzip reader so native member/trailing-byte policy stays
    visible. It reads at most one byte beyond the configured decoded-output ceiling,
    allowing oversized expansion to fail closed without materializing an unbounded
    result. Budget and runtime/zlib identity are immutable replay configuration.
    """

    max_decompressed_bytes: int = DEFAULT_MAX_DECOMPRESSED_BYTES
    _runtime_identity: tuple[str, str, str] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        _validate_max_decompressed_bytes(self.max_decompressed_bytes)
        object.__setattr__(self, "_runtime_identity", _python_runtime_identity())

    @property
    def runtime_identity(self) -> tuple[str, str, str]:
        """Return Python implementation/version and zlib runtime version."""
        return self._runtime_identity

    def as_command_target(self) -> CommandTarget:
        implementation, python_version, zlib_version = self._runtime_identity
        return CommandTarget(
            (
                sys.executable,
                "-m",
                "systems_conformance._gzip_decompression_worker",
                "--max-decompressed-bytes",
                str(self.max_decompressed_bytes),
                "--python-implementation",
                implementation,
                "--python-version",
                python_version,
                "--zlib-version",
                zlib_version,
            )
        )
