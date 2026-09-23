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
const LABEL = __LABEL__;
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
  const decoder = new TextDecoder(LABEL, {
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
    process.stderr.write("utf16_node_runtime_error\n");
    process.exitCode = 3;
  }
}
""".strip()


def _node_script(*, byte_order: str, mode: str, errors: str, chunk_size: int) -> str:
    label = "utf-16le" if byte_order == "le" else "utf-16be"
    return (
        _NODE_SCRIPT.replace("__LABEL__", dumps(label))
        .replace("__MODE__", dumps(mode))
        .replace("__ERRORS__", dumps(errors))
        .replace("__CHUNK_SIZE__", str(chunk_size))
    )


@dataclass(frozen=True, slots=True)
class UTF16NodeDecodeTarget:
    """Node WHATWG TextDecoder target for UTF-16LE/BE interoperability."""

    byte_order: Literal["le", "be"] = "le"
    mode: Literal["oneshot", "incremental"] = "incremental"
    errors: Literal["strict", "replace"] = "strict"
    chunk_size: int = 1
    node_executable: str = "node"

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
        if not isinstance(self.node_executable, str) or not self.node_executable:
            raise ValueError("node_executable must be a non-empty string")
        if which(self.node_executable) is None:
            raise RuntimeError(
                f"Node runtime is required for UTF16NodeDecodeTarget: {self.node_executable}"
            )

    def as_command_target(self) -> CommandTarget:
        return CommandTarget(
            (
                self.node_executable,
                "-e",
                _node_script(
                    byte_order=self.byte_order,
                    mode=self.mode,
                    errors=self.errors,
                    chunk_size=self.chunk_size,
                ),
            )
        )
