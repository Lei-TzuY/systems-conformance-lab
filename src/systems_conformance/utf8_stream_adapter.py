from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import Literal

from .harness import CommandTarget


@dataclass(frozen=True, slots=True)
class UTF8DecodeTarget:
    """Process-isolated UTF-8 decoder conformance target.

    Input bytes are passed directly through stdin; no adapter-local request envelope is
    inserted. The oneshot mode uses bytes.decode while incremental mode feeds the same
    bytes through Python's incremental UTF-8 decoder in fixed-size chunks. The worker
    canonicalizes both successful text and strict decode rejection into JSON so the
    generic differential harness compares semantic output instead of exception details.

    chunk_size affects only incremental decoding. It remains part of argv in both modes
    so target configuration and replay identity stay explicit and immutable.
    """

    mode: Literal["oneshot", "incremental"] = "incremental"
    errors: Literal["strict", "replace", "ignore"] = "strict"
    chunk_size: int = 1

    def __post_init__(self) -> None:
        if self.mode not in {"oneshot", "incremental"}:
            raise ValueError("mode must be 'oneshot' or 'incremental'")
        if self.errors not in {"strict", "replace", "ignore"}:
            raise ValueError("errors must be 'strict', 'replace', or 'ignore'")
        if (
            isinstance(self.chunk_size, bool)
            or not isinstance(self.chunk_size, int)
            or self.chunk_size <= 0
        ):
            raise ValueError("chunk_size must be a positive integer")

    def as_command_target(self) -> CommandTarget:
        """Return the immutable process target used by DifferentialHarness."""
        return CommandTarget(
            (
                sys.executable,
                "-m",
                "systems_conformance._utf8_stream_worker",
                "--mode",
                self.mode,
                "--errors",
                self.errors,
                "--chunk-size",
                str(self.chunk_size),
            )
        )
