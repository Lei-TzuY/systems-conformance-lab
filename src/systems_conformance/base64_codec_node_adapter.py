from __future__ import annotations

import json
from dataclasses import dataclass, field
from json import dumps
from shutil import which
from typing import Literal

from .harness import CommandTarget
from .runner import run_process

_NODE_IDENTITY_SCRIPT = r"""
process.stdout.write(JSON.stringify({
  node: process.version,
}));
""".strip()

_NODE_SCRIPT = r"""
const fs = require("node:fs");

const MODE = __MODE__;
const ALPHABET = __ALPHABET__;
const EXPECTED_NODE_VERSION = __NODE_VERSION__;

function emit(value) {
  process.stdout.write(JSON.stringify(value) + "\n");
}

function hasOnlyAscii(raw) {
  for (const byte of raw) {
    if (byte > 0x7f) {
      return false;
    }
  }
  return true;
}

if (process.version !== EXPECTED_NODE_VERSION) {
  process.stderr.write("base64_codec_runtime_identity_mismatch\n");
  process.exitCode = 3;
} else {
  const raw = fs.readFileSync(0);
  const encoding = ALPHABET === "base64" ? "base64" : "base64url";

  if (MODE === "encode") {
    emit({ encoded: raw.toString(encoding), ok: true });
  } else if (!hasOnlyAscii(raw)) {
    emit({ error: "ascii_decode_error", ok: false });
  } else {
    const text = raw.toString("ascii");
    const decoded = Buffer.from(text, encoding);
    emit({ hex: decoded.toString("hex"), ok: true });
  }
}
""".strip()


def _probe_node_runtime_identity(node_executable: str) -> tuple[str]:
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
        raise RuntimeError("unable to probe Node Base64 runtime identity")

    try:
        payload = json.loads(result.stdout.text)
    except (json.JSONDecodeError, RecursionError) as exc:
        raise RuntimeError("Node Base64 runtime identity probe returned invalid JSON") from exc

    if not isinstance(payload, dict) or set(payload) != {"node"}:
        raise RuntimeError("Node Base64 runtime identity probe returned invalid fields")
    node_version = payload["node"]
    if not isinstance(node_version, str) or not node_version or len(node_version) > 128:
        raise RuntimeError("Node Base64 runtime identity probe returned invalid values")
    return (node_version,)


def _node_script(*, mode: str, alphabet: str, runtime_identity: tuple[str]) -> str:
    (node_version,) = runtime_identity
    return (
        _NODE_SCRIPT.replace("__MODE__", dumps(mode))
        .replace("__ALPHABET__", dumps(alphabet))
        .replace("__NODE_VERSION__", dumps(node_version))
    )


@dataclass(frozen=True, slots=True)
class Base64CodecNodeTarget:
    """Node Buffer Base64/Base64url target with captured runtime identity."""

    mode: Literal["encode", "decode"] = "encode"
    alphabet: Literal["base64", "base64url"] = "base64"
    node_executable: str = "node"
    _runtime_identity: tuple[str] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        if self.mode not in {"encode", "decode"}:
            raise ValueError("mode must be 'encode' or 'decode'")
        if self.alphabet not in {"base64", "base64url"}:
            raise ValueError("alphabet must be 'base64' or 'base64url'")
        if not isinstance(self.node_executable, str) or not self.node_executable:
            raise ValueError("node_executable must be a non-empty string")
        if which(self.node_executable) is None:
            raise RuntimeError(
                "Node runtime is required for Base64CodecNodeTarget: "
                f"{self.node_executable}"
            )
        object.__setattr__(
            self,
            "_runtime_identity",
            _probe_node_runtime_identity(self.node_executable),
        )

    @property
    def runtime_identity(self) -> tuple[str]:
        """Return Node version captured at construction."""
        return self._runtime_identity

    def as_command_target(self) -> CommandTarget:
        return CommandTarget(
            (
                self.node_executable,
                "-e",
                _node_script(
                    mode=self.mode,
                    alphabet=self.alphabet,
                    runtime_identity=self._runtime_identity,
                ),
            )
        )
