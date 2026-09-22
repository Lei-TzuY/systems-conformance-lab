from __future__ import annotations

from dataclasses import dataclass
from json import dumps
from shutil import which
from typing import Literal

from .harness import CommandTarget

_NODE_SCRIPT = r"""
const fs = require("node:fs");
const { TextDecoder } = require("node:util");

const raw = fs.readFileSync(0);
const MODE = __MODE__;
const ERRORS = __ERRORS__;
const CHUNK_SIZE = __CHUNK_SIZE__;

function asciiJsonString(value) {
  const encoded = JSON.stringify(value);
  let output = "";
  for (let index = 0; index < encoded.length; index += 1) {
    const codeUnit = encoded.charCodeAt(index);
    if (codeUnit <= 0x7f) {
      output += encoded[index];
    } else {
      output += "\\u" + codeUnit.toString(16).padStart(4, "0");
    }
  }
  return output;
}

function emitSuccess(text) {
  process.stdout.write('{"ok":true,"text":' + asciiJsonString(text) + '}\n');
}

function emitDecodeError() {
  process.stdout.write('{"error":"unicode_decode_error","ok":false}\n');
}

try {
  const decoder = new TextDecoder("utf-8", {
    fatal: ERRORS === "strict",
    ignoreBOM: true,
  });

  let text = "";
  if (MODE === "oneshot") {
    text = decoder.decode(raw);
  } else {
    for (let start = 0; start < raw.length; start += CHUNK_SIZE) {
      text += decoder.decode(raw.subarray(start, start + CHUNK_SIZE), { stream: true });
    }
    text += decoder.decode();
  }
  emitSuccess(text);
} catch (error) {
  if (ERRORS === "strict" && error instanceof TypeError) {
    emitDecodeError();
  } else {
    process.stderr.write("utf8_node_runtime_error\n");
    process.exitCode = 3;
  }
}
""".strip()


def _node_script(*, mode: str, errors: str, chunk_size: int) -> str:
    return (
        _NODE_SCRIPT.replace("__MODE__", dumps(mode))
        .replace("__ERRORS__", dumps(errors))
        .replace("__CHUNK_SIZE__", str(chunk_size))
    )


@dataclass(frozen=True, slots=True)
class UTF8NodeDecodeTarget:
    """Node/WHATWG TextDecoder target for cross-runtime UTF-8 conformance.

    stdin is the exact byte string under test. The target canonicalizes successful
    decoded text and fatal decode rejection to the same JSON surface as
    UTF8DecodeTarget, allowing DifferentialHarness to compare Python and Node process
    semantics without teaching the generic substrate about Unicode.

    ignoreBOM is enabled intentionally so a leading UTF-8 BOM remains U+FEFF, matching
    Python's plain utf-8 decoder rather than utf-8-sig behavior.
    """

    mode: Literal["oneshot", "incremental"] = "incremental"
    errors: Literal["strict", "replace"] = "strict"
    chunk_size: int = 1
    node_executable: str = "node"

    def __post_init__(self) -> None:
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
        if not isinstance(self.node_executable, str) or not self.node_executable:
            raise ValueError("node_executable must be a non-empty string")
        if which(self.node_executable) is None:
            raise RuntimeError(
                f"Node runtime is required for UTF8NodeDecodeTarget: {self.node_executable}"
            )

    def as_command_target(self) -> CommandTarget:
        """Return the immutable Node process target used by DifferentialHarness."""
        return CommandTarget(
            (
                self.node_executable,
                "-e",
                _node_script(
                    mode=self.mode,
                    errors=self.errors,
                    chunk_size=self.chunk_size,
                ),
            )
        )
