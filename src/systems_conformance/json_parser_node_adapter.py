from __future__ import annotations

import json
from dataclasses import dataclass, field
from json import dumps
from shutil import which

from .harness import CommandTarget
from .json_parser_adapter import (
    DEFAULT_MAX_JSON_DOCUMENT_BYTES,
    MAX_CONFIGURED_JSON_DOCUMENT_BYTES,
)
from .runner import run_process

_NODE_IDENTITY_SCRIPT = r"""
process.stdout.write(JSON.stringify({node: process.version}));
""".strip()

_NODE_SCRIPT = r"""
const fs = require("node:fs");
const { TextDecoder } = require("node:util");

const EXPECTED_NODE_VERSION = __NODE_VERSION__;
const MAX_DOCUMENT_BYTES = __MAX_DOCUMENT_BYTES__;

function canonicalize(value) {
  if (Array.isArray(value)) {
    return value.map(canonicalize);
  }
  if (value !== null && typeof value === "object") {
    const result = {};
    for (const key of Object.keys(value).sort()) {
      result[key] = canonicalize(value[key]);
    }
    return result;
  }
  return value;
}

function emit(value) {
  process.stdout.write(JSON.stringify(canonicalize(value)) + "\n");
}

function hasNonFinite(value) {
  if (typeof value === "number") {
    return !Number.isFinite(value);
  }
  if (Array.isArray(value)) {
    return value.some(hasNonFinite);
  }
  if (value !== null && typeof value === "object") {
    return Object.values(value).some(hasNonFinite);
  }
  return false;
}

function readBoundedStdin(limit) {
  const chunks = [];
  let total = 0;

  while (true) {
    const remaining = limit + 1 - total;
    if (remaining <= 0) {
      return null;
    }
    const buffer = Buffer.allocUnsafe(Math.min(64 * 1024, remaining));
    const count = fs.readSync(0, buffer, 0, buffer.length, null);
    if (count === 0) {
      break;
    }
    total += count;
    if (total > limit) {
      return null;
    }
    chunks.push(buffer.subarray(0, count));
  }

  return Buffer.concat(chunks, total);
}

if (process.version !== EXPECTED_NODE_VERSION) {
  process.stderr.write("json_parser_runtime_identity_mismatch\n");
  process.exitCode = 3;
} else {
  const raw = readBoundedStdin(MAX_DOCUMENT_BYTES);
  if (raw === null) {
    emit({error: "input_too_large", ok: false});
  } else {
    let text;
    try {
      text = new TextDecoder("utf-8", {fatal: true, ignoreBOM: true}).decode(raw);
    } catch (_) {
      emit({error: "utf8_decode_error", ok: false});
      process.exit(0);
    }

    let value;
    try {
      value = JSON.parse(text);
    } catch (_) {
      emit({error: "json_parse_error", ok: false});
      process.exit(0);
    }

    try {
      if (hasNonFinite(value)) {
        emit({error: "non_finite_number", ok: false});
      } else {
        emit({ok: true, value});
      }
    } catch (_) {
      emit({error: "json_result_error", ok: false});
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
        raise RuntimeError("unable to probe Node JSON runtime identity")
    try:
        payload = json.loads(result.stdout.text)
    except (json.JSONDecodeError, RecursionError) as exc:
        raise RuntimeError("Node JSON runtime identity probe returned invalid JSON") from exc
    if not isinstance(payload, dict) or set(payload) != {"node"}:
        raise RuntimeError("Node JSON runtime identity probe returned invalid fields")
    node_version = payload["node"]
    if not isinstance(node_version, str) or not node_version or len(node_version) > 128:
        raise RuntimeError("Node JSON runtime identity probe returned invalid values")
    return (node_version,)


def _node_script(*, runtime_identity: tuple[str], max_document_bytes: int) -> str:
    (node_version,) = runtime_identity
    return (
        _NODE_SCRIPT.replace("__NODE_VERSION__", dumps(node_version))
        .replace("__MAX_DOCUMENT_BYTES__", str(max_document_bytes))
    )


@dataclass(frozen=True, slots=True)
class JSONParseNodeTarget:
    """Node JSON.parse target over bounded strict UTF-8 stdin."""

    max_document_bytes: int = DEFAULT_MAX_JSON_DOCUMENT_BYTES
    node_executable: str = "node"
    _runtime_identity: tuple[str] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        if isinstance(self.max_document_bytes, bool) or not isinstance(
            self.max_document_bytes, int
        ):
            raise TypeError("max_document_bytes must be an integer")
        if (
            self.max_document_bytes < 0
            or self.max_document_bytes > MAX_CONFIGURED_JSON_DOCUMENT_BYTES
        ):
            raise ValueError(
                "max_document_bytes must be between 0 and "
                f"{MAX_CONFIGURED_JSON_DOCUMENT_BYTES}"
            )
        if not isinstance(self.node_executable, str) or not self.node_executable:
            raise ValueError("node_executable must be a non-empty string")
        if which(self.node_executable) is None:
            raise RuntimeError(
                "Node runtime is required for JSONParseNodeTarget: "
                f"{self.node_executable}"
            )
        object.__setattr__(
            self,
            "_runtime_identity",
            _probe_node_runtime_identity(self.node_executable),
        )

    @property
    def runtime_identity(self) -> tuple[str]:
        return self._runtime_identity

    def as_command_target(self) -> CommandTarget:
        return CommandTarget(
            (
                self.node_executable,
                "-e",
                _node_script(
                    runtime_identity=self._runtime_identity,
                    max_document_bytes=self.max_document_bytes,
                ),
            )
        )
