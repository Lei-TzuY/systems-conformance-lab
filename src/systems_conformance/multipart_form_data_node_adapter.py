from __future__ import annotations

import json
from dataclasses import dataclass, field
from json import dumps
from shutil import which

from .harness import CommandTarget
from .multipart_form_data_adapter import (
    DEFAULT_MAX_MULTIPART_BODY_BYTES,
    MAX_CONFIGURED_MULTIPART_BODY_BYTES,
    MULTIPART_FORM_DATA_BOUNDARY,
)
from .runner import run_process

_NODE_IDENTITY_SCRIPT = r"""
process.stdout.write(JSON.stringify({
  node: process.version,
  undici: process.versions.undici,
}));
""".strip()

_NODE_SCRIPT = r"""
const fs = require("node:fs");

const EXPECTED_NODE_VERSION = __NODE_VERSION__;
const EXPECTED_UNDICI_VERSION = __UNDICI_VERSION__;
const MAX_BODY_BYTES = __MAX_BODY_BYTES__;
const BOUNDARY = __BOUNDARY__;

function emit(value) {
  process.stdout.write(JSON.stringify(value) + "\n");
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

async function main() {
  if (
    process.version !== EXPECTED_NODE_VERSION ||
    process.versions.undici !== EXPECTED_UNDICI_VERSION
  ) {
    process.stderr.write("multipart_form_data_runtime_identity_mismatch\n");
    process.exitCode = 3;
    return;
  }

  const raw = readBoundedStdin(MAX_BODY_BYTES);
  if (raw === null) {
    emit({error: "input_too_large", ok: false});
    return;
  }

  try {
    const response = new Response(raw, {
      headers: {
        "content-type": "multipart/form-data; boundary=\"" + BOUNDARY + "\"",
      },
    });
    const form = await response.formData();
    const entries = [];

    for (const [name, value] of form.entries()) {
      const nameHex = Buffer.from(name, "utf8").toString("hex");
      if (typeof value === "string") {
        entries.push({
          kind: "text",
          name_utf8_hex: nameHex,
          value_utf8_hex: Buffer.from(value, "utf8").toString("hex"),
        });
        continue;
      }

      const body = Buffer.from(await value.arrayBuffer());
      entries.push({
        body_hex: body.toString("hex"),
        content_type: value.type,
        filename_utf8_hex: Buffer.from(value.name, "utf8").toString("hex"),
        kind: "file",
        name_utf8_hex: nameHex,
      });
    }

    emit({entries, ok: true});
  } catch (_) {
    emit({error: "multipart_parse_error", ok: false});
  }
}

main().catch(() => {
  process.stderr.write("multipart_form_data_worker_unexpected_error\n");
  process.exitCode = 4;
});
""".strip()


def _validate_max_body_bytes(value: object) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError("max_body_bytes must be an integer")
    if value < 0 or value > MAX_CONFIGURED_MULTIPART_BODY_BYTES:
        raise ValueError(
            "max_body_bytes must be between 0 and "
            f"{MAX_CONFIGURED_MULTIPART_BODY_BYTES}"
        )


def _probe_node_runtime_identity(node_executable: str) -> tuple[str, str]:
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
        raise RuntimeError("unable to probe Node multipart runtime identity")

    try:
        payload = json.loads(result.stdout.text)
    except (json.JSONDecodeError, RecursionError) as exc:
        raise RuntimeError(
            "Node multipart runtime identity probe returned invalid JSON"
        ) from exc

    if not isinstance(payload, dict) or set(payload) != {"node", "undici"}:
        raise RuntimeError(
            "Node multipart runtime identity probe returned invalid fields"
        )
    node_version = payload["node"]
    undici_version = payload["undici"]
    if (
        not isinstance(node_version, str)
        or not node_version
        or len(node_version) > 128
        or not isinstance(undici_version, str)
        or not undici_version
        or len(undici_version) > 128
    ):
        raise RuntimeError(
            "Node multipart runtime identity probe returned invalid values"
        )
    return node_version, undici_version


def _node_script(
    *,
    max_body_bytes: int,
    runtime_identity: tuple[str, str],
) -> str:
    node_version, undici_version = runtime_identity
    return (
        _NODE_SCRIPT.replace("__NODE_VERSION__", dumps(node_version))
        .replace("__UNDICI_VERSION__", dumps(undici_version))
        .replace("__MAX_BODY_BYTES__", str(max_body_bytes))
        .replace("__BOUNDARY__", dumps(MULTIPART_FORM_DATA_BOUNDARY))
    )


@dataclass(frozen=True, slots=True)
class MultipartFormDataNodeTarget:
    """Node Response.formData target over bounded raw multipart body bytes."""

    max_body_bytes: int = DEFAULT_MAX_MULTIPART_BODY_BYTES
    node_executable: str = "node"
    _runtime_identity: tuple[str, str] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        _validate_max_body_bytes(self.max_body_bytes)
        if not isinstance(self.node_executable, str) or not self.node_executable:
            raise ValueError("node_executable must be a non-empty string")
        if which(self.node_executable) is None:
            raise RuntimeError(
                "Node runtime is required for MultipartFormDataNodeTarget: "
                f"{self.node_executable}"
            )
        object.__setattr__(
            self,
            "_runtime_identity",
            _probe_node_runtime_identity(self.node_executable),
        )

    @property
    def runtime_identity(self) -> tuple[str, str]:
        return self._runtime_identity

    def as_command_target(self) -> CommandTarget:
        return CommandTarget(
            (
                self.node_executable,
                "-e",
                _node_script(
                    max_body_bytes=self.max_body_bytes,
                    runtime_identity=self._runtime_identity,
                ),
            )
        )
