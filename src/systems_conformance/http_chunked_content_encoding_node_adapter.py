from __future__ import annotations

import json
from dataclasses import dataclass, field
from json import dumps
from shutil import which

from .harness import CommandTarget
from .http_chunked_content_encoding_adapter import (
    DEFAULT_MAX_OBSERVED_BODY_BYTES,
    DEFAULT_MAX_TRANSFER_BODY_BYTES,
    MAX_CONFIGURED_BODY_BYTES,
)
from .runner import run_process

_NODE_IDENTITY_SCRIPT = r"""
process.stdout.write(JSON.stringify({
  node: process.version,
  undici: process.versions.undici,
  zlib: process.versions.zlib,
}));
""".strip()

_NODE_SCRIPT = r"""
const net = require("node:net");

const MAX_TRANSFER_BODY_BYTES = __MAX_TRANSFER_BODY_BYTES__;
const MAX_OBSERVED_BODY_BYTES = __MAX_OBSERVED_BODY_BYTES__;
const EXPECTED_NODE_VERSION = __NODE_VERSION__;
const EXPECTED_UNDICI_VERSION = __UNDICI_VERSION__;
const EXPECTED_ZLIB_VERSION = __ZLIB_VERSION__;
const IDENTITY = 0;
const GZIP = 1;

function emit(value) {
  process.stdout.write(JSON.stringify(value) + "\n");
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

function parseCase(raw) {
  if (raw.length === 0) {
    return null;
  }

  const mode = raw[0];
  if (mode !== IDENTITY && mode !== GZIP) {
    return null;
  }

  return {
    contentEncoding: mode === GZIP ? "gzip" : null,
    transferBody: raw.subarray(1),
  };
}

async function listenLoopback(server) {
  return await new Promise((resolve, reject) => {
    const onError = (error) => {
      server.off("listening", onListening);
      reject(error);
    };
    const onListening = () => {
      server.off("error", onError);
      resolve(server.address());
    };
    server.once("error", onError);
    server.once("listening", onListening);
    server.listen(0, "127.0.0.1");
  });
}

async function closeServer(server) {
  await new Promise((resolve) => {
    server.close(() => resolve());
  });
}

async function readObservedBody(response) {
  if (response.body === null) {
    throw new Error("missing response body");
  }

  const reader = response.body.getReader();
  const chunks = [];
  let total = 0;

  while (true) {
    const { done, value } = await reader.read();
    if (done) {
      break;
    }
    total += value.byteLength;
    if (total > MAX_OBSERVED_BODY_BYTES) {
      await reader.cancel();
      return null;
    }
    chunks.push(Buffer.from(value));
  }

  return Buffer.concat(chunks, total);
}

async function fetchLoopback(parsed) {
  const headerLines = [
    "HTTP/1.1 200 OK",
    "Content-Type: application/octet-stream",
    "Transfer-Encoding: chunked",
  ];
  if (parsed.contentEncoding !== null) {
    headerLines.push("Content-Encoding: gzip");
  }
  headerLines.push("Connection: close", "", "");

  const responsePrefix = Buffer.from(headerLines.join("\r\n"), "ascii");

  const server = net.createServer((socket) => {
    let request = Buffer.alloc(0);
    socket.setTimeout(5000, () => socket.destroy());

    socket.on("data", (chunk) => {
      request = Buffer.concat([request, chunk]);
      if (request.length > 64 * 1024) {
        socket.destroy();
        return;
      }
      if (request.includes(Buffer.from("\r\n\r\n", "ascii"))) {
        socket.end(Buffer.concat([responsePrefix, parsed.transferBody]));
      }
    });
  });

  let address;
  try {
    address = await listenLoopback(server);
  } catch (error) {
    emit({ error: "loopback_server_error", ok: false });
    return;
  }

  try {
    let response;
    try {
      response = await fetch(`http://127.0.0.1:${address.port}/`);
    } catch (error) {
      emit({ error: "http_fetch_error", ok: false });
      return;
    }

    const transferEncoding = response.headers.get("transfer-encoding");
    const contentEncoding = response.headers.get("content-encoding");
    const contentLength = response.headers.get("content-length");

    let observed;
    try {
      observed = await readObservedBody(response);
    } catch (error) {
      emit({ error: "body_decode_error", ok: false });
      return;
    }

    if (observed === null) {
      emit({ error: "observed_body_too_large", ok: false });
      return;
    }

    emit({
      body_hex: observed.toString("hex"),
      content_encoding: contentEncoding,
      content_length: contentLength,
      ok: true,
      transfer_encoding: transferEncoding,
    });
  } finally {
    await closeServer(server);
  }
}

async function main() {
  if (
    process.version !== EXPECTED_NODE_VERSION ||
    process.versions.undici !== EXPECTED_UNDICI_VERSION ||
    process.versions.zlib !== EXPECTED_ZLIB_VERSION
  ) {
    process.stderr.write(
      "http_chunked_content_encoding_runtime_identity_mismatch\n"
    );
    process.exitCode = 3;
    return;
  }

  const raw = await readBoundedStdin(MAX_TRANSFER_BODY_BYTES + 1);
  if (raw === null) {
    emit({ error: "transfer_body_too_large", ok: false });
    return;
  }

  const parsed = parseCase(raw);
  if (parsed === null) {
    emit({ error: "protocol_error", ok: false });
    return;
  }

  await fetchLoopback(parsed);
}

main().catch(() => {
  process.stderr.write(
    "http_chunked_content_encoding_worker_unexpected_error\n"
  );
  process.exitCode = 4;
});
""".strip()


def _validate_budget(name: str, value: object) -> None:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value <= 0
        or value > MAX_CONFIGURED_BODY_BYTES
    ):
        raise ValueError(
            f"{name} must be an integer between 1 and {MAX_CONFIGURED_BODY_BYTES}"
        )


def _probe_node_runtime_identity(node_executable: str) -> tuple[str, str, str]:
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
        raise RuntimeError(
            "unable to probe Node HTTP chunked content-encoding runtime identity"
        )

    try:
        payload = json.loads(result.stdout.text)
    except (json.JSONDecodeError, RecursionError) as exc:
        raise RuntimeError(
            "Node HTTP chunked content-encoding runtime identity probe "
            "returned invalid JSON"
        ) from exc

    if not isinstance(payload, dict) or set(payload) != {"node", "undici", "zlib"}:
        raise RuntimeError(
            "Node HTTP chunked content-encoding runtime identity probe "
            "returned invalid fields"
        )

    values = payload["node"], payload["undici"], payload["zlib"]
    if any(
        not isinstance(value, str) or not value or len(value) > 128
        for value in values
    ):
        raise RuntimeError(
            "Node HTTP chunked content-encoding runtime identity probe "
            "returned invalid values"
        )
    return values


def _node_script(
    *,
    max_transfer_body_bytes: int,
    max_observed_body_bytes: int,
    runtime_identity: tuple[str, str, str],
) -> str:
    node_version, undici_version, zlib_version = runtime_identity
    return (
        _NODE_SCRIPT.replace(
            "__MAX_TRANSFER_BODY_BYTES__", str(max_transfer_body_bytes)
        )
        .replace("__MAX_OBSERVED_BODY_BYTES__", str(max_observed_body_bytes))
        .replace("__NODE_VERSION__", dumps(node_version))
        .replace("__UNDICI_VERSION__", dumps(undici_version))
        .replace("__ZLIB_VERSION__", dumps(zlib_version))
    )


@dataclass(frozen=True, slots=True)
class HTTPChunkedContentEncodingNodeTarget:
    """Node Fetch target for chunked plus Content-Encoding response semantics."""

    max_transfer_body_bytes: int = DEFAULT_MAX_TRANSFER_BODY_BYTES
    max_observed_body_bytes: int = DEFAULT_MAX_OBSERVED_BODY_BYTES
    node_executable: str = "node"
    _runtime_identity: tuple[str, str, str] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        _validate_budget("max_transfer_body_bytes", self.max_transfer_body_bytes)
        _validate_budget("max_observed_body_bytes", self.max_observed_body_bytes)
        if not isinstance(self.node_executable, str) or not self.node_executable:
            raise ValueError("node_executable must be a non-empty string")
        if which(self.node_executable) is None:
            raise RuntimeError(
                "Node runtime is required for HTTPChunkedContentEncodingNodeTarget: "
                f"{self.node_executable}"
            )
        object.__setattr__(
            self,
            "_runtime_identity",
            _probe_node_runtime_identity(self.node_executable),
        )

    @property
    def runtime_identity(self) -> tuple[str, str, str]:
        return self._runtime_identity

    def as_command_target(self) -> CommandTarget:
        return CommandTarget(
            (
                self.node_executable,
                "-e",
                _node_script(
                    max_transfer_body_bytes=self.max_transfer_body_bytes,
                    max_observed_body_bytes=self.max_observed_body_bytes,
                    runtime_identity=self._runtime_identity,
                ),
            )
        )
