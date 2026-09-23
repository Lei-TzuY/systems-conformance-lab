from __future__ import annotations

from dataclasses import dataclass
from json import dumps
from shutil import which
from typing import Literal

from .harness import CommandTarget

_NORMALIZATION_FORMS = frozenset({"NFC", "NFD", "NFKC", "NFKD"})

_NODE_SCRIPT = r"""
const fs = require("node:fs");
const { TextDecoder } = require("node:util");

const raw = fs.readFileSync(0);
const FORM = __FORM__;

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
    fatal: true,
    ignoreBOM: true,
  });
  emitSuccess(decoder.decode(raw).normalize(FORM));
} catch (error) {
  if (error instanceof TypeError) {
    emitDecodeError();
  } else {
    process.stderr.write("unicode_normalization_node_runtime_error\n");
    process.exitCode = 3;
  }
}
""".strip()


def _node_script(*, form: str) -> str:
    return _NODE_SCRIPT.replace("__FORM__", dumps(form))


@dataclass(frozen=True, slots=True)
class UnicodeNodeNormalizationTarget:
    """Node String.normalize target over strict UTF-8 stdin.

    Node's fatal WHATWG TextDecoder maps invalid UTF-8 to the same canonical rejection
    used by the Python target. A successful decode is normalized with
    String.prototype.normalize using one of the four standard forms.

    ignoreBOM is enabled so a leading UTF-8 BOM remains U+FEFF, matching Python's plain
    utf-8 decoder. The runtime executable and normalization form are both target
    configuration and therefore participate in replay identity.
    """

    form: Literal["NFC", "NFD", "NFKC", "NFKD"] = "NFC"
    node_executable: str = "node"

    def __post_init__(self) -> None:
        if self.form not in _NORMALIZATION_FORMS:
            raise ValueError("form must be 'NFC', 'NFD', 'NFKC', or 'NFKD'")
        if not isinstance(self.node_executable, str) or not self.node_executable:
            raise ValueError("node_executable must be a non-empty string")
        if which(self.node_executable) is None:
            raise RuntimeError(
                "Node runtime is required for UnicodeNodeNormalizationTarget: "
                f"{self.node_executable}"
            )

    def as_command_target(self) -> CommandTarget:
        """Return the immutable Node normalization process target."""

        return CommandTarget(
            (
                self.node_executable,
                "-e",
                _node_script(form=self.form),
            )
        )
