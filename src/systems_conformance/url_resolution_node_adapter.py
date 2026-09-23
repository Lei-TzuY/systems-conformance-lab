from __future__ import annotations

import json
from dataclasses import dataclass, field
from json import dumps
from shutil import which

from .harness import CommandTarget
from .runner import run_process

_NODE_IDENTITY_SCRIPT = 'process.stdout.write(JSON.stringify({node: process.version}));'

_NODE_SCRIPT = r"""
const fs = require("node:fs");
const { TextDecoder } = require("node:util");

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

function emitRequestError() {
  emit({
    error: "request_error",
    ok: false,
  });
}

function emitDecodeError() {
  emit({
    error: "unicode_decode_error",
    ok: false,
  });
}

function emitParseError() {
  emit({
    error: "url_parse_error",
    ok: false,
  });
}

function isHttpUrl(parsed) {
  return (
    (parsed.protocol === "http:" || parsed.protocol === "https:") &&
    parsed.hostname !== ""
  );
}

function project(parsed) {
  return {
    fragment: parsed.hash === "" ? "" : parsed.hash.slice(1),
    hostname: parsed.hostname,
    ok: true,
    password: parsed.password,
    path: parsed.pathname,
    port: parsed.port,
    query: parsed.search === "" ? "" : parsed.search.slice(1),
    scheme: parsed.protocol.slice(0, -1),
    username: parsed.username,
  };
}

if (process.version !== EXPECTED_NODE_VERSION) {
  process.stderr.write("url_resolution_runtime_identity_mismatch\n");
  process.exitCode = 3;
} else {
  const raw = fs.readFileSync(0);
  if (raw.length < 4) {
    emitRequestError();
  } else {
    const baseLength = raw.readUInt32BE(0);
    const payloadLength = raw.length - 4;
    if (baseLength > payloadLength) {
      emitRequestError();
    } else {
      const decoder = new TextDecoder("utf-8", {
        fatal: true,
        ignoreBOM: true,
      });
      let base;
      let reference;
      try {
        base = decoder.decode(raw.subarray(4, 4 + baseLength));
        reference = new TextDecoder("utf-8", {
          fatal: true,
          ignoreBOM: true,
        }).decode(raw.subarray(4 + baseLength));
      } catch (error) {
        if (error instanceof TypeError) {
          emitDecodeError();
        } else {
          process.stderr.write("url_resolution_node_runtime_error\n");
          process.exitCode = 3;
        }
      }

      if (base !== undefined && reference !== undefined) {
        try {
          const parsedBase = new URL(base);
          if (!isHttpUrl(parsedBase)) {
            throw new TypeError("out-of-scope base URL");
          }
          const resolved = new URL(reference, parsedBase);
          if (!isHttpUrl(resolved)) {
            throw new TypeError("out-of-scope resolved URL");
          }
          emit(project(resolved));
        } catch (error) {
          if (error instanceof TypeError) {
            emitParseError();
          } else {
            process.stderr.write("url_resolution_node_runtime_error\n");
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
        raise RuntimeError("unable to probe Node URL resolution runtime identity")

    try:
        payload = json.loads(result.stdout.text)
    except (json.JSONDecodeError, RecursionError) as exc:
        raise RuntimeError(
            "Node URL resolution runtime identity probe returned invalid JSON"
        ) from exc

    if not isinstance(payload, dict) or set(payload) != {"node"}:
        raise RuntimeError("Node URL resolution runtime identity probe returned invalid fields")
    node_version = payload["node"]
    if not isinstance(node_version, str) or not node_version or len(node_version) > 128:
        raise RuntimeError("Node URL resolution runtime identity probe returned invalid value")
    return (node_version,)


def _node_script(runtime_identity: tuple[str]) -> str:
    (node_version,) = runtime_identity
    return _NODE_SCRIPT.replace("__NODE_VERSION__", dumps(node_version))


@dataclass(frozen=True, slots=True)
class URLNodeResolutionTarget:
    """Node WHATWG URL target for relative-reference resolution interoperability."""

    node_executable: str = "node"
    _runtime_identity: tuple[str] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.node_executable, str) or not self.node_executable:
            raise ValueError("node_executable must be a non-empty string")
        if which(self.node_executable) is None:
            raise RuntimeError(
                f"Node runtime is required for URLNodeResolutionTarget: "
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
                _node_script(self._runtime_identity),
            )
        )
