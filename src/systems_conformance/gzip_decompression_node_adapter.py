from __future__ import annotations

import json
from dataclasses import dataclass, field
from json import dumps
from shutil import which

from .gzip_decompression_adapter import (
    DEFAULT_MAX_DECOMPRESSED_BYTES,
    MAX_CONFIGURED_DECOMPRESSED_BYTES,
)
from .harness import CommandTarget
from .runner import run_process

_NODE_IDENTITY_SCRIPT = r"""
process.stdout.write(JSON.stringify({
  node: process.version,
  zlib: process.versions.zlib,
}));
""".strip()

_NODE_SCRIPT = r"""
const fs = require("node:fs");
const zlib = require("node:zlib");

const MAX_DECOMPRESSED_BYTES = __MAX_DECOMPRESSED_BYTES__;
const EXPECTED_NODE_VERSION = __NODE_VERSION__;
const EXPECTED_ZLIB_VERSION = __ZLIB_VERSION__;

function emit(value) {
  process.stdout.write(JSON.stringify(value) + "\n");
}

if (
  process.version !== EXPECTED_NODE_VERSION ||
  process.versions.zlib !== EXPECTED_ZLIB_VERSION
) {
  process.stderr.write("gzip_runtime_identity_mismatch\n");
  process.exitCode = 3;
} else {
  const raw = fs.readFileSync(0);

  try {
    const decoded = zlib.gunzipSync(raw, {
      maxOutputLength: MAX_DECOMPRESSED_BYTES + 1,
    });
    if (decoded.length > MAX_DECOMPRESSED_BYTES) {
      emit({ error: "decompressed_output_too_large", ok: false });
    } else {
      emit({ hex: decoded.toString("hex"), ok: true });
    }
  } catch (error) {
    if (error && error.code === "ERR_BUFFER_TOO_LARGE") {
      emit({ error: "decompressed_output_too_large", ok: false });
    } else {
      emit({ error: "gzip_decode_error", ok: false });
    }
  }
}
""".strip()


def _validate_max_decompressed_bytes(value: object) -> None:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value <= 0
        or value > MAX_CONFIGURED_DECOMPRESSED_BYTES
    ):
        raise ValueError(
            "max_decompressed_bytes must be an integer between 1 and "
            f"{MAX_CONFIGURED_DECOMPRESSED_BYTES}"
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
        raise RuntimeError("unable to probe Node gzip runtime identity")

    try:
        payload = json.loads(result.stdout.text)
    except (json.JSONDecodeError, RecursionError) as exc:
        raise RuntimeError("Node gzip runtime identity probe returned invalid JSON") from exc

    if not isinstance(payload, dict) or set(payload) != {"node", "zlib"}:
        raise RuntimeError("Node gzip runtime identity probe returned invalid fields")
    node_version = payload["node"]
    zlib_version = payload["zlib"]
    if (
        not isinstance(node_version, str)
        or not node_version
        or len(node_version) > 128
        or not isinstance(zlib_version, str)
        or not zlib_version
        or len(zlib_version) > 128
    ):
        raise RuntimeError("Node gzip runtime identity probe returned invalid values")
    return node_version, zlib_version


def _node_script(
    *,
    max_decompressed_bytes: int,
    runtime_identity: tuple[str, str],
) -> str:
    node_version, zlib_version = runtime_identity
    return (
        _NODE_SCRIPT.replace(
            "__MAX_DECOMPRESSED_BYTES__",
            str(max_decompressed_bytes),
        )
        .replace("__NODE_VERSION__", dumps(node_version))
        .replace("__ZLIB_VERSION__", dumps(zlib_version))
    )


@dataclass(frozen=True, slots=True)
class GzipDecompressionNodeTarget:
    """Node zlib gzip decompression target with a hard output ceiling."""

    max_decompressed_bytes: int = DEFAULT_MAX_DECOMPRESSED_BYTES
    node_executable: str = "node"
    _runtime_identity: tuple[str, str] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        _validate_max_decompressed_bytes(self.max_decompressed_bytes)
        if not isinstance(self.node_executable, str) or not self.node_executable:
            raise ValueError("node_executable must be a non-empty string")
        if which(self.node_executable) is None:
            raise RuntimeError(
                "Node runtime is required for GzipDecompressionNodeTarget: "
                f"{self.node_executable}"
            )
        object.__setattr__(
            self,
            "_runtime_identity",
            _probe_node_runtime_identity(self.node_executable),
        )

    @property
    def runtime_identity(self) -> tuple[str, str]:
        """Return Node and zlib runtime versions captured at construction."""
        return self._runtime_identity

    def as_command_target(self) -> CommandTarget:
        return CommandTarget(
            (
                self.node_executable,
                "-e",
                _node_script(
                    max_decompressed_bytes=self.max_decompressed_bytes,
                    runtime_identity=self._runtime_identity,
                ),
            )
        )
