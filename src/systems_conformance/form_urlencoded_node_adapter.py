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
const { TextDecoder } = require("node:util");

const MODE = __MODE__;
const EXPECTED_NODE_VERSION = __NODE_VERSION__;

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

function requestError() {
  emit({
    error: "request_error",
    ok: false,
  });
}

function unicodeDecodeError() {
  emit({
    error: "unicode_decode_error",
    ok: false,
  });
}

function decodeUtf8(buffer) {
  return new TextDecoder("utf-8", {
    fatal: true,
    ignoreBOM: true,
  }).decode(buffer);
}

function decodePairs(raw) {
  let offset = 0;

  function readU32() {
    const end = offset + 4;
    if (end > raw.length) {
      throw new RangeError("truncated framing");
    }
    const value = raw.readUInt32BE(offset);
    offset = end;
    return value;
  }

  const pairCount = readU32();
  if (pairCount > Math.floor((raw.length - offset) / 8)) {
    throw new RangeError("pair count exceeds framing");
  }

  const pairs = [];
  for (let index = 0; index < pairCount; index += 1) {
    const keyLength = readU32();
    const keyEnd = offset + keyLength;
    if (keyEnd > raw.length) {
      throw new RangeError("key length exceeds framing");
    }
    const keyRaw = raw.subarray(offset, keyEnd);
    offset = keyEnd;

    const valueLength = readU32();
    const valueEnd = offset + valueLength;
    if (valueEnd > raw.length) {
      throw new RangeError("value length exceeds framing");
    }
    const valueRaw = raw.subarray(offset, valueEnd);
    offset = valueEnd;

    pairs.push([decodeUtf8(keyRaw), decodeUtf8(valueRaw)]);
  }

  if (offset !== raw.length) {
    throw new RangeError("trailing bytes");
  }
  return pairs;
}

if (process.version !== EXPECTED_NODE_VERSION) {
  process.stderr.write("form_urlencoded_runtime_identity_mismatch\n");
  process.exitCode = 3;
} else {
  const raw = fs.readFileSync(0);

  if (MODE === "encode") {
    let pairs;
    try {
      pairs = decodePairs(raw);
    } catch (error) {
      if (error instanceof RangeError) {
        requestError();
      } else if (error instanceof TypeError) {
        unicodeDecodeError();
      } else {
        process.stderr.write("form_urlencoded_node_runtime_error\n");
        process.exitCode = 3;
      }
    }

    if (pairs !== undefined) {
      emit({
        form: new URLSearchParams(pairs).toString(),
        ok: true,
      });
    }
  } else {
    let text;
    try {
      text = decodeUtf8(raw);
    } catch (error) {
      if (error instanceof TypeError) {
        unicodeDecodeError();
      } else {
        process.stderr.write("form_urlencoded_node_runtime_error\n");
        process.exitCode = 3;
      }
    }

    if (text !== undefined) {
      emit({
        ok: true,
        pairs: Array.from(new URLSearchParams(text).entries()),
      });
    }
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
        raise RuntimeError("unable to probe Node form-urlencoded runtime identity")

    try:
        payload = json.loads(result.stdout.text)
    except (json.JSONDecodeError, RecursionError) as exc:
        raise RuntimeError(
            "Node form-urlencoded runtime identity probe returned invalid JSON"
        ) from exc

    if not isinstance(payload, dict) or set(payload) != {"node"}:
        raise RuntimeError(
            "Node form-urlencoded runtime identity probe returned invalid fields"
        )
    node_version = payload["node"]
    if not isinstance(node_version, str) or not node_version or len(node_version) > 128:
        raise RuntimeError(
            "Node form-urlencoded runtime identity probe returned invalid values"
        )
    return (node_version,)


def _node_script(*, mode: str, runtime_identity: tuple[str]) -> str:
    (node_version,) = runtime_identity
    return (
        _NODE_SCRIPT.replace("__MODE__", dumps(mode))
        .replace("__NODE_VERSION__", dumps(node_version))
    )


@dataclass(frozen=True, slots=True)
class FormURLEncodedNodeTarget:
    """Node URLSearchParams application/x-www-form-urlencoded target."""

    mode: Literal["encode", "decode"] = "encode"
    node_executable: str = "node"
    _runtime_identity: tuple[str] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        if self.mode not in {"encode", "decode"}:
            raise ValueError("mode must be 'encode' or 'decode'")
        if not isinstance(self.node_executable, str) or not self.node_executable:
            raise ValueError("node_executable must be a non-empty string")
        if which(self.node_executable) is None:
            raise RuntimeError(
                "Node runtime is required for FormURLEncodedNodeTarget: "
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
                    runtime_identity=self._runtime_identity,
                ),
            )
        )
