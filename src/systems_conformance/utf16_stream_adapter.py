from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import Literal

from .harness import CommandTarget


@dataclass(frozen=True, slots=True)
class UTF16DecodeTarget:
    """Python UTF-16LE/BE streaming decoder over raw stdin bytes.

    Byte order is explicit rather than BOM-selected. A BOM is therefore decoded as
    U+FEFF and preserved in the semantic output. Incremental mode feeds arbitrary byte
    chunk sizes through Python's incremental codec, including splits inside two-byte
    code units and four-byte surrogate pairs.

    Byte order, mode, error policy, and chunk size are immutable process configuration
    and therefore participate in replay identity.
    """

    byte_order: Literal["le", "be"] = "le"
    mode: Literal["oneshot", "incremental"] = "incremental"
    errors: Literal["strict", "replace"] = "strict"
    chunk_size: int = 1

    def __post_init__(self) -> None:
        if self.byte_order not in {"le", "be"}:
            raise ValueError("byte_order must be 'le' or 'be'")
        if self.mode not in {"oneshot", "incremental"}:
            raise ValueError("mode must be 'oneshot' or 'incremental'")
        if self.errors not in {"strict", "replace"}:
            raise ValueError("errors must be 'strict' or 'replace'")
        if (
            isinstance(self.chunk_size, bool)
            or not isinstance(self.chunk_size, int)
            or self.chunk_size <= 0
        ):
            raise ValueError("chunk_size must be a positive integer")

    def as_command_target(self) -> CommandTarget:
        return CommandTarget(
            (
                sys.executable,
                "-m",
                "systems_conformance._utf16_stream_worker",
                "--byte-order",
                self.byte_order,
                "--mode",
                self.mode,
                "--errors",
                self.errors,
                "--chunk-size",
                str(self.chunk_size),
            )
        )
