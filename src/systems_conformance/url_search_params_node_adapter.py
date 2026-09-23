from __future__ import annotations

import json
from dataclasses import dataclass, field
from json import dumps
from shutil import which

from .harness import CommandTarget
from .runner import run_process
from .url_search_params_adapter import (
    DEFAULT_MAX_FIELD_BYTES,
    DEFAULT_MAX_INITIAL_PAIRS,
    DEFAULT_MAX_OPERATIONS,
)

_NODE_IDENTITY_SCRIPT = 'process.stdout.write(JSON.stringify({node: process.version}));'

_NODE_SCRIPT = r"""
const fs = require("node:fs");
const { TextDecoder } = require("node:util");

const EXPECTED_NODE_VERSION = __NODE_VERSION__;
const MAX_INITIAL_PAIRS = __MAX_INITIAL_PAIRS__;
const MAX_OPERATIONS = __MAX_OPERATIONS__;
const MAX_FIELD_BYTES = __MAX_FIELD_BYTES__;

const APPEND = 1;
const SET = 2;
const DELETE = 3;
const SORT = 4;

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

function decodeRequest(raw) {
  let offset = 0;
  const decoder = new TextDecoder("utf-8", {
    fatal: true,
    ignoreBOM: true,
  });

  function readU32() {
    const end = offset + 4;
    if (end > raw.length) {
      throw new RangeError("truncated framing");
    }
    const value = raw.readUInt32BE(offset);
    offset = end;
    return value;
  }

  function readField() {
    const length = readU32();
    if (length > MAX_FIELD_BYTES) {
      throw new RangeError("field exceeds max_field_bytes");
    }
    const end = offset + length;
    if (end > raw.length) {
      throw new RangeError("field length exceeds framing");
    }
    const value = decoder.decode(raw.subarray(offset, end));
    offset = end;
    return value;
  }

  const pairCount = readU32();
  if (pairCount > MAX_INITIAL_PAIRS) {
    throw new RangeError("pair count exceeds budget");
  }

  const pairs = [];
  for (let index = 0; index < pairCount; index += 1) {
    pairs.push([readField(), readField()]);
  }

  const operationCount = readU32();
  if (operationCount > MAX_OPERATIONS) {
    throw new RangeError("operation count exceeds budget");
  }

  const operations = [];
  for (let index = 0; index < operationCount; index += 1) {
    if (offset >= raw.length) {
      throw new RangeError("truncated operation");
    }
    const opcode = raw[offset];
    offset += 1;

    if (opcode === APPEND || opcode === SET) {
      operations.push([opcode, readField(), readField()]);
    } else if (opcode === DELETE) {
      operations.push([opcode, readField()]);
    } else if (opcode === SORT) {
      operations.push([opcode]);
    } else {
      throw new RangeError("unsupported operation opcode");
    }
  }

  if (offset !== raw.length) {
    throw new RangeError("trailing bytes");
  }
  return { pairs, operations };
}

if (process.version !== EXPECTED_NODE_VERSION) {
  process.stderr.write("url_search_params_runtime_identity_mismatch\n");
  process.exitCode = 3;
} else {
  const raw = fs.readFileSync(0);
  let request;

  try {
    request = decodeRequest(raw);
  } catch (error) {
    if (error instanceof TypeError) {
      emit({
        error: "unicode_decode_error",
        ok: false,
      });
    } else if (error instanceof RangeError) {
      emit({
        error: "request_error",
        ok: false,
      });
    } else {
      process.stderr.write("url_search_params_node_runtime_error\n");
      process.exitCode = 3;
    }
  }

  if (request !== undefined) {
    const params = new URLSearchParams(request.pairs);

    for (const operation of request.operations) {
      if (operation[0] === APPEND) {
        params.append(operation[1], operation[2]);
      } else if (operation[0] === SET) {
        params.set(operation[1], operation[2]);
      } else if (operation[0] === DELETE) {
        params.delete(operation[1]);
      } else if (operation[0] === SORT) {
        params.sort();
      }
    }

    emit({
      ok: true,
      pairs: Array.from(params.entries()),
      query: params.toString(),
    });
  }
}
""".strip()


def _validate_positive_integer(name: str, value: object) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{name} must be a positive integer")


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
        raise RuntimeError("unable to probe Node URLSearchParams runtime identity")

    try:
        payload = json.loads(result.stdout.text)
    except (json.JSONDecodeError, RecursionError) as exc:
        raise RuntimeError(
            "Node URLSearchParams runtime identity probe returned invalid JSON"
        ) from exc

    if not isinstance(payload, dict) or set(payload) != {"node"}:
        raise RuntimeError(
            "Node URLSearchParams runtime identity probe returned invalid fields"
        )
    node_version = payload["node"]
    if not isinstance(node_version, str) or not node_version or len(node_version) > 128:
        raise RuntimeError(
            "Node URLSearchParams runtime identity probe returned invalid value"
        )
    return (node_version,)


def _node_script(
    *,
    runtime_identity: tuple[str],
    max_initial_pairs: int,
    max_operations: int,
    max_field_bytes: int,
) -> str:
    (node_version,) = runtime_identity
    return (
        _NODE_SCRIPT.replace("__NODE_VERSION__", dumps(node_version))
        .replace("__MAX_INITIAL_PAIRS__", str(max_initial_pairs))
        .replace("__MAX_OPERATIONS__", str(max_operations))
        .replace("__MAX_FIELD_BYTES__", str(max_field_bytes))
    )


@dataclass(frozen=True, slots=True)
class URLSearchParamsNodeTarget:
    """Node WHATWG URLSearchParams stateful mutation target."""

    max_initial_pairs: int = DEFAULT_MAX_INITIAL_PAIRS
    max_operations: int = DEFAULT_MAX_OPERATIONS
    max_field_bytes: int = DEFAULT_MAX_FIELD_BYTES
    node_executable: str = "node"
    _runtime_identity: tuple[str] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        _validate_positive_integer("max_initial_pairs", self.max_initial_pairs)
        _validate_positive_integer("max_operations", self.max_operations)
        _validate_positive_integer("max_field_bytes", self.max_field_bytes)
        if not isinstance(self.node_executable, str) or not self.node_executable:
            raise ValueError("node_executable must be a non-empty string")
        if which(self.node_executable) is None:
            raise RuntimeError(
                "Node runtime is required for URLSearchParamsNodeTarget: "
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
                    max_initial_pairs=self.max_initial_pairs,
                    max_operations=self.max_operations,
                    max_field_bytes=self.max_field_bytes,
                ),
            )
        )
