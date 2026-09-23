from __future__ import annotations

import json
from dataclasses import dataclass, field
from json import dumps
from shutil import which

from .harness import CommandTarget
from .runner import run_process

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
const { domainToASCII } = require("node:url");

const EXPECTED_NODE_VERSION = __NODE_VERSION__;
const EXPECTED_ICU_VERSION = __ICU_VERSION__;
const EXPECTED_UNICODE_VERSION = __UNICODE_VERSION__;

function asciiJson(value) {
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

function emit(value) {
  process.stdout.write(asciiJson(value) + "\n");
}

if (
  process.version !== EXPECTED_NODE_VERSION ||
  process.versions.icu !== EXPECTED_ICU_VERSION ||
  process.versions.unicode !== EXPECTED_UNICODE_VERSION
) {
  process.stderr.write("idna_hostname_runtime_identity_mismatch\n");
  process.exitCode = 3;
} else {
  const raw = fs.readFileSync(0);
  let hostname;
  try {
    hostname = new TextDecoder("utf-8", {
      fatal: true,
      ignoreBOM: true,
    }).decode(raw);
  } catch (error) {
    if (error instanceof TypeError) {
      emit({
        error: "unicode_decode_error",
        ok: false,
      });
    } else {
      process.stderr.write("idna_hostname_node_runtime_error\n");
      process.exitCode = 3;
    }
  }

  if (hostname !== undefined) {
    if (hostname === "") {
      emit({
        error: "idna_error",
        ok: false,
      });
    } else {
      const ascii = domainToASCII(hostname);
      if (ascii === "") {
        emit({
          error: "idna_error",
          ok: false,
        });
      } else {
        emit({
          ascii,
          ok: true,
        });
      }
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
        raise RuntimeError("unable to probe Node IDNA runtime identity")

    try:
        payload = json.loads(result.stdout.text)
    except (json.JSONDecodeError, RecursionError) as exc:
        raise RuntimeError("Node IDNA runtime identity probe returned invalid JSON") from exc

    if not isinstance(payload, dict) or set(payload) != {"node", "icu", "unicode"}:
        raise RuntimeError("Node IDNA runtime identity probe returned invalid fields")
    node_version = payload["node"]
    icu_version = payload["icu"]
    unicode_version = payload["unicode"]
    values = (node_version, icu_version, unicode_version)
    if any(not isinstance(value, str) or not value or len(value) > 128 for value in values):
        raise RuntimeError("Node IDNA runtime identity probe returned invalid values")
    assert isinstance(node_version, str)
    assert isinstance(icu_version, str)
    assert isinstance(unicode_version, str)
    return node_version, icu_version, unicode_version


def _node_script(runtime_identity: tuple[str, str, str]) -> str:
    node_version, icu_version, unicode_version = runtime_identity
    return (
        _NODE_SCRIPT.replace("__NODE_VERSION__", dumps(node_version))
        .replace("__ICU_VERSION__", dumps(icu_version))
        .replace("__UNICODE_VERSION__", dumps(unicode_version))
    )


@dataclass(frozen=True, slots=True)
class IDNANodeHostnameTarget:
    """Node WHATWG domain-to-ASCII target over strict UTF-8 stdin."""

    node_executable: str = "node"
    _runtime_identity: tuple[str, str, str] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.node_executable, str) or not self.node_executable:
            raise ValueError("node_executable must be a non-empty string")
        if which(self.node_executable) is None:
            raise RuntimeError(
                f"Node runtime is required for IDNANodeHostnameTarget: {self.node_executable}"
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
        return CommandTarget(
            (
                self.node_executable,
                "-e",
                _node_script(self._runtime_identity),
            )
        )
