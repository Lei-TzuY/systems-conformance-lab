from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import Literal

from ._utf8_chunking import encode_chunk_pattern, validate_chunk_pattern
from .harness import CommandTarget


@dataclass(frozen=True, slots=True)
class UTF8DecodeTarget:
    """Process-isolated UTF-8 decoder conformance target.

    Input bytes are passed directly through stdin; no adapter-local request envelope is
    inserted. The oneshot mode uses bytes.decode while incremental mode feeds the same
    bytes through Python's incremental UTF-8 decoder. By default segmentation remains
    the legacy fixed chunk_size policy; an explicit chunk_pattern cycles through a
    bounded irregular sequence until the input is exhausted.

    The worker canonicalizes both successful text and strict decode rejection into JSON
    so the generic differential harness compares semantic output instead of exception
    details. Segmentation configuration is carried in argv, keeping replay identity
    explicit and immutable.
    """

    mode: Literal["oneshot", "incremental"] = "incremental"
    errors: Literal["strict", "replace", "ignore"] = "strict"
    chunk_size: int = 1
    chunk_pattern: tuple[int, ...] | None = None

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
        validate_chunk_pattern(self.chunk_pattern)

    def as_command_target(self) -> CommandTarget:
        """Return the immutable process target used by DifferentialHarness."""

        argv = [
            sys.executable,
            "-m",
            "systems_conformance._utf8_stream_worker",
            "--mode",
            self.mode,
            "--errors",
            self.errors,
            "--chunk-size",
            str(self.chunk_size),
        ]
        if self.chunk_pattern is not None:
            argv.extend(
                (
                    "--chunk-pattern",
                    encode_chunk_pattern(self.chunk_pattern),
                )
            )
        return CommandTarget(tuple(argv))
