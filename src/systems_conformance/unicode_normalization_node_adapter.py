from __future__ import annotations

import json
from dataclasses import dataclass, field
from json import dumps
from shutil import which
from typing import Literal

from .harness import CommandTarget
from .runner import run_process

_NORMALIZATION_FORMS = frozenset({"NFC", "NFD", "NFKC", "NFKD"})

_NODE_IDENTITY_SCRIPT = r"""
process.stdout.write(JSON.stringify({
  node: process.version,
  icu: process.versions.icu,
  unicode: process.versions.unicode,
}));
""".strip()

_NODE_SCRIPT = r"""
const fs = require("node:fs");
const { TextDecoder } = require("node:util");

const FORM = __FORM__;
const EXPECTED_NODE_VERSION = __NODE_VERSION__;
const EXPECTED_ICU_VERSION = __ICU_VERSION__;
const EXPECTED_UNICODE_VERSION = __UNICODE_VERSION__;

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

if (
  process.version !== EXPECTED_NODE_VERSION ||
  process.versions.icu !== EXPECTED_ICU_VERSION ||
  process.versions.unicode !== EXPECTED_UNICODE_VERSION
) {
  process.stderr.write("unicode_normalization_runtime_identity_mismatch\n");
  process.exitCode = 3;
} else {
  const raw = fs.readFileSync(0);
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
}
""".strip()


def _probe_node_runtime_identity(node_executable: str) -> tuple[str, str, str]:
    result = run_process(
        (node_executable, "-e", _NODE_IDENTITY_SCRIPT),
        timeout_seconds=5.0,
        max_input_bytes=0,
        max_output_bytes=1024,
        max_total_output_bytes=2048,
    )
    if (
        result.infrastructure_error is not None
        or result.timed_out
        or result.exit_code != 0
        or result.stdout.truncated
        or result.stderr.total_bytes != 0
    ):
        raise RuntimeError("unable to probe Node Unicode runtime identity")

    try:
        payload = json.loads(result.stdout.text)
    except (json.JSONDecodeError, RecursionError) as exc:
        raise RuntimeError("Node Unicode runtime identity probe returned invalid JSON") from exc

    if not isinstance(payload, dict) or set(payload) != {"node", "icu", "unicode"}:
        raise RuntimeError("Node Unicode runtime identity probe returned invalid fields")
    node_version = payload["node"]
    icu_version = payload["icu"]
    unicode_version = payload["unicode"]
    values = (node_version, icu_version, unicode_version)
    if any(not isinstance(value, str) or not value or len(value) > 128 for value in values):
        raise RuntimeError("Node Unicode runtime identity probe returned invalid values")
    assert isinstance(node_version, str)
    assert isinstance(icu_version, str)
    assert isinstance(unicode_version, str)
    return node_version, icu_version, unicode_version


def _node_script(
    *,
    form: str,
    runtime_identity: tuple[str, str, str],
) -> str:
    node_version, icu_version, unicode_version = runtime_identity
    return (
        _NODE_SCRIPT.replace("__FORM__", dumps(form))
        .replace("__NODE_VERSION__", dumps(node_version))
        .replace("__ICU_VERSION__", dumps(icu_version))
        .replace("__UNICODE_VERSION__", dumps(unicode_version))
    )


@dataclass(frozen=True, slots=True)
class UnicodeNodeNormalizationTarget:
    """Node String.normalize target over strict UTF-8 stdin.

    Node's fatal WHATWG TextDecoder maps invalid UTF-8 to the same canonical rejection
    used by the Python target. A successful decode is normalized with
    String.prototype.normalize using one of the four standard forms.

    ignoreBOM is enabled so a leading UTF-8 BOM remains U+FEFF, matching Python's plain
    utf-8 decoder. Construction probes Node through the shared bounded process runner
    and captures Node, ICU, and Unicode versions. Those values are embedded in the
    target script, participate in replay identity, and are verified again by the child
    before it consumes case bytes.
    """

    form: Literal["NFC", "NFD", "NFKC", "NFKD"] = "NFC"
    node_executable: str = "node"
    _runtime_identity: tuple[str, str, str] = field(init=False, repr=False)

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
        object.__setattr__(
            self,
            "_runtime_identity",
            _probe_node_runtime_identity(self.node_executable),
        )

    @property
    def runtime_identity(self) -> tuple[str, str, str]:
        """Return Node, ICU, and Unicode versions captured at construction."""
        return self._runtime_identity

    def as_command_target(self) -> CommandTarget:
        """Return the immutable Node normalization process target."""

        return CommandTarget(
            (
                self.node_executable,
                "-e",
                _node_script(
                    form=self.form,
                    runtime_identity=self._runtime_identity,
                ),
            )
        )
