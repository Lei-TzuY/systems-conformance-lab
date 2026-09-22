# UTF-8 streaming conformance adapter

UTF8DecodeTarget is the repository's second concrete conformance-domain adapter. Unlike
the SQLite adapters, its case bytes are not wrapped in JSON: stdin is the exact byte
sequence under test. This exercises the generic process and differential substrate with
arbitrary binary input rather than a target-specific request envelope.

The target has two execution modes:

- oneshot decodes the complete byte string with bytes.decode;
- incremental feeds the same byte string through Python's incremental UTF-8 decoder in
  fixed-size chunks and finalizes the decoder explicitly.

Supported error policies are strict, replace, and ignore. The worker canonicalizes
successful text and strict rejection into deterministic JSON. It deliberately does not
persist exception offsets or CPython-specific error wording; the conformance claim in
this phase is acceptance/rejection plus decoded text semantics.

## Executable boundary

The integration suite compares incremental execution against one-shot execution through
DifferentialHarness across:

- valid ASCII and multibyte UTF-8 split at one-, two-, three-, and seven-byte chunks;
- invalid leading and continuation bytes;
- truncated two-, three-, and four-byte sequences at finalization;
- replace and ignore policies across multiple chunk sizes;
- a finite DeterministicByteMutations corpus containing multibyte seeds.

The fuzz regression exhausts the configured deterministic byte schedule and requires
every case to remain a differential match. This is a second-domain integration of the
existing generic fuzz scheduler, not a new UTF-8-specific fuzz engine.

## Scope boundary

This phase does not claim Unicode normalization, locale behavior, UTF-16/UTF-32,
grapheme segmentation, transcoding, or cross-runtime interoperability. Both decoder
paths are provided by Python's standard library. The architectural result is narrower:
the shared runner, harness, comparator, replay identity, and deterministic fuzz
interfaces now execute a non-SQLite raw-byte streaming domain without absorbing codec
semantics into the generic core.


## Cross-runtime interoperability

The next executable layer compares the existing Python decoder with Node 22's WHATWG
TextDecoder through the same DifferentialHarness. Node is provisioned explicitly in CI;
the adapter fails closed at construction when its runtime executable is unavailable.

The Node target supports the shared strict and replace policies. Its fatal option maps
strict decode rejection to the same canonical JSON error used by the Python worker.
ignoreBOM is set to true so a leading UTF-8 BOM remains U+FEFF, matching Python's plain
utf-8 decoder. The Python-only ignore policy is intentionally outside the cross-runtime
claim.

The cross-runtime suite executes both one-shot and incremental modes across multibyte
chunk boundaries, BOM input, invalid and truncated byte sequences, replacement cases,
and a finite deterministic strict-mode byte mutation schedule. Candidate and oracle are
separate Node and Python child processes; a passing result therefore exercises process
execution, canonical output, comparison, and fuzz scheduling across two language
runtimes rather than two APIs in one runtime.

This phase does not claim that every implementation-specific replacement policy or
Unicode service is identical. Unicode normalization, locale behavior, grapheme
segmentation, UTF-16/UTF-32, and broad ICU interoperability remain separate surfaces.
