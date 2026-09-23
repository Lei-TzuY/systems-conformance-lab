from __future__ import annotations

import json
from dataclasses import dataclass, field
from json import dumps
from shutil import which

from .data_url_fetch_adapter import (
    DEFAULT_MAX_DATA_URL_BYTES,
    MAX_CONFIGURED_DATA_URL_BYTES,
)
from .harness import CommandTarget
from .runner import run_process

_NODE_IDENTITY_SCRIPT = r"""
process.stdout.write(JSON.stringify({
  node: process.version,
  undici: process.versions.undici,
}));
""".strip()

_NODE_SCRIPT = r"""
const MAX_DATA_URL_BYTES = __MAX_DATA_URL_BYTES__;
const EXPECTED_NODE_VERSION = __NODE_VERSION__;
const EXPECTED_UNDICI_VERSION = __UNDICI_VERSION__;

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

async function readBoundedStdin(limit) {
  const chunks = [];
  let total = 0;

  for await (const chunk of process.stdin) {
    total += chunk.length;
    if (total > limit) {
      return null;
    }
    chunks.push(chunk);
  }

  return Buffer.concat(chunks, total);
}

async function main() {
  if (
    process.version !== EXPECTED_NODE_VERSION ||
    process.versions.undici !== EXPECTED_UNDICI_VERSION
  ) {
    process.stderr.write("data_url_runtime_identity_mismatch\n");
    process.exitCode = 3;
    return;
  }

  const raw = await readBoundedStdin(MAX_DATA_URL_BYTES);
  if (raw === null) {
    emit({ error: "data_url_too_large", ok: false });
    return;
  }
  if (!hasOnlyAscii(raw)) {
    emit({ error: "ascii_decode_error", ok: false });
    return;
  }

  const text = raw.toString("ascii");
  if (text.slice(0, 5).toLowerCase() !== "data:") {
    emit({ error: "unsupported_scheme", ok: false });
    return;
  }

  try {
    const response = await fetch(text);
    const body = Buffer.from(await response.arrayBuffer());
    if (body.length > MAX_DATA_URL_BYTES) {
      emit({ error: "decoded_body_too_large", ok: false });
      return;
    }
    const contentType = response.headers.get("content-type");
    if (typeof contentType !== "string") {
      emit({ error: "data_url_error", ok: false });
      return;
    }
    emit({
      body_hex: body.toString("hex"),
      content_type: contentType,
      ok: true,
    });
  } catch (error) {
    emit({ error: "data_url_error", ok: false });
  }
}

main().catch((error) => {
  process.stderr.write("data_url_worker_unexpected_error\n");
  process.exitCode = 4;
});
""".strip()


def _validate_max_data_url_bytes(value: object) -> None:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value <= 0
        or value > MAX_CONFIGURED_DATA_URL_BYTES
    ):
        raise ValueError(
            "max_data_url_bytes must be an integer between 1 and "
            f"{MAX_CONFIGURED_DATA_URL_BYTES}"
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
        raise RuntimeError("unable to probe Node data URL runtime identity")

    try:
        payload = json.loads(result.stdout.text)
    except (json.JSONDecodeError, RecursionError) as exc:
        raise RuntimeError(
            "Node data URL runtime identity probe returned invalid JSON"
        ) from exc

    if not isinstance(payload, dict) or set(payload) != {"node", "undici"}:
        raise RuntimeError(
            "Node data URL runtime identity probe returned invalid fields"
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
            "Node data URL runtime identity probe returned invalid values"
        )
    return node_version, undici_version


def _node_script(
    *,
    max_data_url_bytes: int,
    runtime_identity: tuple[str, str],
) -> str:
    node_version, undici_version = runtime_identity
    return (
        _NODE_SCRIPT.replace("__MAX_DATA_URL_BYTES__", str(max_data_url_bytes))
        .replace("__NODE_VERSION__", dumps(node_version))
        .replace("__UNDICI_VERSION__", dumps(undici_version))
    )


@dataclass(frozen=True, slots=True)
class DataURLFetchNodeTarget:
    """Node fetch(data:) target with a hard input ceiling and runtime identity."""

    max_data_url_bytes: int = DEFAULT_MAX_DATA_URL_BYTES
    node_executable: str = "node"
    _runtime_identity: tuple[str, str] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        _validate_max_data_url_bytes(self.max_data_url_bytes)
        if not isinstance(self.node_executable, str) or not self.node_executable:
            raise ValueError("node_executable must be a non-empty string")
        if which(self.node_executable) is None:
            raise RuntimeError(
                "Node runtime is required for DataURLFetchNodeTarget: "
                f"{self.node_executable}"
            )
        object.__setattr__(
            self,
            "_runtime_identity",
            _probe_node_runtime_identity(self.node_executable),
        )

    @property
    def runtime_identity(self) -> tuple[str, str]:
        """Return Node and Undici versions captured at construction."""
        return self._runtime_identity

    def as_command_target(self) -> CommandTarget:
        return CommandTarget(
            (
                self.node_executable,
                "-e",
                _node_script(
                    max_data_url_bytes=self.max_data_url_bytes,
                    runtime_identity=self._runtime_identity,
                ),
            )
        )
