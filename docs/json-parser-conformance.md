# Bounded JSON parser interoperability

This phase adds a real cross-runtime structured-data parser boundary. Python's standard-library `json.loads` and Node's native `JSON.parse` execute as separate child-process targets above the existing runner, differential harness, failure discovery, repro, and replay substrate.

## Input and isolation contract

Both targets consume exact stdin bytes and apply strict UTF-8 decoding before JSON parsing. Invalid UTF-8 is projected to the same bounded semantic rejection instead of relying on runtime-specific replacement decoding. Each adapter carries an immutable `max_document_bytes` value into the child process, capped at 1 MiB. Each worker reads at most one byte beyond that ceiling and rejects an oversized document immediately, without requiring stdin EOF, before JSON parsing. The harness still supplies its independent process timeout, stdin ceiling, per-stream capture ceiling, aggregate emitted-output ceiling, and process-tree cleanup.

No shell interpolation is used. Runtime identity and the document budget are process argv configuration, so the existing replay-context fingerprint binds them automatically.

## Semantic result surface

Successful parses emit a deterministic JSON record of the form `{"ok":true,"value":...}`. Object keys are recursively ordered before Node serialization and Python uses sorted-key serialization, keeping ordinary shared-subset results stable. Parse, UTF-8, input-budget, and Python non-finite-number rejections use bounded error records.

The adapter deliberately does not coerce runtime number semantics into a common artificial model. In particular, Python preserves arbitrary-size JSON integers while Node represents JSON numbers as IEEE-754 `Number`. The document `{"n":9007199254740993}` therefore provides a deterministic product-mismatch witness: Python preserves `9007199254740993`, while Node rounds it to `9007199254740992`. Python's stdlib parser also accepts non-standard `NaN` by default; the worker recognizes the resulting non-finite value and reports it explicitly, while Node rejects the token during parsing. These are product-policy differences, not infrastructure failures.

## Validation

Focused integration tests cover null/boolean/integer/string/array/object/Unicode shared cases, malformed JSON, BOM rejection, invalid UTF-8, exact target-level input budgeting, runtime-identity drift, replay-context changes, large-integer precision divergence, and Python's non-standard `NaN` acceptance. A deterministic two-case discovery campaign reaches the large-integer mismatch, persists the exact input and failure signature as a repro bundle, and replays it through the same real Python/Node targets.

The CI workflow already provisions Node 22 on every supported OS/Python matrix entry, so this target is exercised as real interoperability rather than conditionally skipped when Node is absent.
