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
  v8: process.versions.v8,
}));
""".strip()

_NODE_SCRIPT = r"""
const fs = require("node:fs");

const EXPECTED_NODE_VERSION = __NODE_VERSION__;
const EXPECTED_V8_VERSION = __V8_VERSION__;

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

function hasExplicitTimezone(text) {
  return /(?:Z|[+-]\d{2}(?::?\d{2})?(?::?\d{2}(?:[.,]\d+)?)?)$/.test(text);
}

if (
  process.version !== EXPECTED_NODE_VERSION ||
  process.versions.v8 !== EXPECTED_V8_VERSION
) {
  process.stderr.write("iso_timestamp_runtime_identity_mismatch\n");
  process.exitCode = 3;
} else {
  const raw = fs.readFileSync(0);

  if (!hasOnlyAscii(raw)) {
    emit({ error: "ascii_decode_error", ok: false });
  } else {
    const text = raw.toString("ascii");
    const epochMilliseconds = Date.parse(text);

    if (Number.isNaN(epochMilliseconds)) {
      emit({ error: "iso_timestamp_parse_error", ok: false });
    } else if (!hasExplicitTimezone(text)) {
      emit({ error: "timezone_required", ok: false });
    } else {
      emit({
        epoch_milliseconds: epochMilliseconds,
        iso_utc: new Date(epochMilliseconds).toISOString(),
        ok: true,
      });
    }
  }
}
""".strip()


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
        raise RuntimeError("unable to probe Node ISO timestamp runtime identity")

    try:
        payload = json.loads(result.stdout.text)
    except (json.JSONDecodeError, RecursionError) as exc:
        raise RuntimeError(
            "Node ISO timestamp runtime identity probe returned invalid JSON"
        ) from exc

    if not isinstance(payload, dict) or set(payload) != {"node", "v8"}:
        raise RuntimeError(
            "Node ISO timestamp runtime identity probe returned invalid fields"
        )
    node_version = payload["node"]
    v8_version = payload["v8"]
    if (
        not isinstance(node_version, str)
        or not node_version
        or len(node_version) > 128
        or not isinstance(v8_version, str)
        or not v8_version
        or len(v8_version) > 128
    ):
        raise RuntimeError(
            "Node ISO timestamp runtime identity probe returned invalid values"
        )
    return (node_version, v8_version)


def _node_script(*, runtime_identity: tuple[str, str]) -> str:
    node_version, v8_version = runtime_identity
    return (
        _NODE_SCRIPT.replace("__NODE_VERSION__", dumps(node_version))
        .replace("__V8_VERSION__", dumps(v8_version))
    )


@dataclass(frozen=True, slots=True)
class ISOTimestampNodeTarget:
    """Node Date.parse ISO timestamp target with captured runtime identity."""

    node_executable: str = "node"
    _runtime_identity: tuple[str, str] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.node_executable, str) or not self.node_executable:
            raise ValueError("node_executable must be a non-empty string")
        if which(self.node_executable) is None:
            raise RuntimeError(
                "Node runtime is required for ISOTimestampNodeTarget: "
                f"{self.node_executable}"
            )
        object.__setattr__(
            self,
            "_runtime_identity",
            _probe_node_runtime_identity(self.node_executable),
        )

    @property
    def runtime_identity(self) -> tuple[str, str]:
        """Return Node and V8 versions captured at construction."""
        return self._runtime_identity

    def as_command_target(self) -> CommandTarget:
        return CommandTarget(
            (
                self.node_executable,
                "-e",
                _node_script(runtime_identity=self._runtime_identity),
            )
        )
