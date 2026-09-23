from __future__ import annotations

import json
from dataclasses import dataclass, field
from json import dumps
from shutil import which

from .harness import CommandTarget
from .json_value_adapter import (
    DEFAULT_MAX_JSON_BYTES,
    DEFAULT_MAX_JSON_DEPTH,
    DEFAULT_MAX_JSON_NODES,
    _validate_positive_integer,
)
from .runner import run_process

_NODE_IDENTITY_SCRIPT = 'process.stdout.write(JSON.stringify({node: process.version}));'

_NODE_SCRIPT = r"""
const fs = require("node:fs");
const { TextDecoder } = require("node:util");

const EXPECTED_NODE_VERSION = __NODE_VERSION__;
const MAX_JSON_BYTES = __MAX_JSON_BYTES__;
const MAX_DEPTH = __MAX_DEPTH__;
const MAX_NODES = __MAX_NODES__;

class ValueBudgetError extends Error {}

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

function readBoundedStdin(maxBytes) {
  const chunks = [];
  let total = 0;
  while (total <= maxBytes) {
    const size = Math.min(8192, maxBytes + 1 - total);
    if (size <= 0) {
      break;
    }
    const chunk = Buffer.allocUnsafe(size);
    const count = fs.readSync(0, chunk, 0, size, null);
    if (count === 0) {
      break;
    }
    chunks.push(chunk.subarray(0, count));
    total += count;
  }
  return Buffer.concat(chunks, total);
}

function canonicalNumber(value) {
  if (Number.isNaN(value)) {
    return "NaN";
  }
  if (value === Infinity) {
    return "Infinity";
  }
  if (value === -Infinity) {
    return "-Infinity";
  }
  return JSON.stringify(value);
}

function keyOrder(value) {
  return asciiJson(value);
}

function projectValue(value) {
  let nodes = 0;

  function project(current, depth) {
    if (depth > MAX_DEPTH) {
      throw new ValueBudgetError("JSON value exceeds max depth");
    }
    nodes += 1;
    if (nodes > MAX_NODES) {
      throw new ValueBudgetError("JSON value exceeds max nodes");
    }

    if (current === null) {
      return ["null"];
    }
    if (typeof current === "boolean") {
      return ["bool", current];
    }
    if (typeof current === "number") {
      return ["number", canonicalNumber(current)];
    }
    if (typeof current === "string") {
      return ["string", current];
    }
    if (Array.isArray(current)) {
      return ["array", current.map((item) => project(item, depth + 1))];
    }
    if (typeof current === "object") {
      const keys = Object.keys(current).sort((left, right) => {
        const a = keyOrder(left);
        const b = keyOrder(right);
        return a < b ? -1 : a > b ? 1 : 0;
      });
      return [
        "object",
        keys.map((key) => [key, project(current[key], depth + 1)]),
      ];
    }
    throw new TypeError("unsupported JSON value type");
  }

  return project(value, 0);
}

if (process.version !== EXPECTED_NODE_VERSION) {
  process.stderr.write("json_value_runtime_identity_mismatch\n");
  process.exitCode = 3;
} else {
  const raw = readBoundedStdin(MAX_JSON_BYTES);
  if (raw.length > MAX_JSON_BYTES) {
    emit({
      error: "input_budget_error",
      ok: false,
    });
  } else {
    let text;
    try {
      const decoder = new TextDecoder("utf-8", {
        fatal: true,
        ignoreBOM: true,
      });
      text = decoder.decode(raw);
    } catch (error) {
      if (error instanceof TypeError) {
        emit({
          error: "unicode_decode_error",
          ok: false,
        });
      } else {
        process.stderr.write("json_value_node_runtime_error\n");
        process.exitCode = 3;
      }
    }

    if (text !== undefined) {
      let parsed;
      try {
        parsed = JSON.parse(text);
      } catch (error) {
        if (error instanceof SyntaxError) {
          emit({
            error: "json_parse_error",
            ok: false,
          });
        } else {
          process.stderr.write("json_value_node_runtime_error\n");
          process.exitCode = 3;
        }
      }

      if (parsed !== undefined) {
        try {
          emit({
            ok: true,
            value: projectValue(parsed),
          });
        } catch (error) {
          if (error instanceof ValueBudgetError || error instanceof RangeError) {
            emit({
              error: "value_budget_error",
              ok: false,
            });
          } else {
            process.stderr.write("json_value_node_runtime_error\n");
            process.exitCode = 3;
          }
        }
      }
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
        raise RuntimeError("unable to probe Node JSON value runtime identity")

    try:
        payload = json.loads(result.stdout.text)
    except (json.JSONDecodeError, RecursionError) as exc:
        raise RuntimeError("Node JSON value runtime identity probe returned invalid JSON") from exc

    if not isinstance(payload, dict) or set(payload) != {"node"}:
        raise RuntimeError("Node JSON value runtime identity probe returned invalid fields")
    node_version = payload["node"]
    if not isinstance(node_version, str) or not node_version or len(node_version) > 128:
        raise RuntimeError("Node JSON value runtime identity probe returned invalid value")
    return (node_version,)


def _node_script(
    runtime_identity: tuple[str],
    *,
    max_json_bytes: int,
    max_depth: int,
    max_nodes: int,
) -> str:
    (node_version,) = runtime_identity
    return (
        _NODE_SCRIPT.replace("__NODE_VERSION__", dumps(node_version))
        .replace("__MAX_JSON_BYTES__", str(max_json_bytes))
        .replace("__MAX_DEPTH__", str(max_depth))
        .replace("__MAX_NODES__", str(max_nodes))
    )


@dataclass(frozen=True, slots=True)
class JSONNodeValueTarget:
    """Node JSON.parse target for cross-runtime JSON value semantics."""

    node_executable: str = "node"
    max_json_bytes: int = DEFAULT_MAX_JSON_BYTES
    max_depth: int = DEFAULT_MAX_JSON_DEPTH
    max_nodes: int = DEFAULT_MAX_JSON_NODES
    _runtime_identity: tuple[str] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.node_executable, str) or not self.node_executable:
            raise ValueError("node_executable must be a non-empty string")
        _validate_positive_integer("max_json_bytes", self.max_json_bytes)
        _validate_positive_integer("max_depth", self.max_depth)
        _validate_positive_integer("max_nodes", self.max_nodes)
        if which(self.node_executable) is None:
            raise RuntimeError(
                f"Node runtime is required for JSONNodeValueTarget: {self.node_executable}"
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
                    self._runtime_identity,
                    max_json_bytes=self.max_json_bytes,
                    max_depth=self.max_depth,
                    max_nodes=self.max_nodes,
                ),
            )
        )
