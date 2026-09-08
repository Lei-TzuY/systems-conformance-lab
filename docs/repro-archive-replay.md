# Portable repro archive replay

`replay_repro_archive` composes the portable archive boundary with `DifferentialHarness` replay without requiring callers to publish an imported bundle into their retained repro directory.

The source archive is read once into a bounded immutable byte snapshot. Replay records the SHA-256 digest of those exact transport bytes in `ArchiveReproReplay.archive_sha256`, and callers may supply `expected_archive_sha256` to pin the artifact being replayed. Expected digests must be lowercase 64-character SHA-256 hex strings. A digest mismatch fails before bundle import and before either untrusted target can execute.

The exact same immutable snapshot then traverses `import_repro_archive` inside a private temporary directory. That preserves the existing exact-member, regular-file, `ZIP_STORED`, encryption, size, input digest, manifest-schema, and semantic-consistency checks while ensuring the digest evidence and imported ZIP cannot refer to different reads of a mutable source path. Only after that import succeeds does the private bundle traverse `DifferentialHarness.replay_repro`.

Replay-context validation therefore still happens before untrusted `input.bin` executes. A context mismatch fails without launching either candidate or oracle. Invalid archives and transport-digest mismatches likewise fail during the archive/bundle validation boundary before target execution.

Callers that use archive replay as a conformance gate can set `require_reproduction=True`. After a valid archive is executed, the fresh run must preserve the archived exact stable `FailureSignature`; otherwise replay raises `RuntimeError` instead of allowing a stale witness to look successful. The gate is independent of `require_same_context`: portability experiments may deliberately replay under a different harness context while still requiring the transported witness to reproduce its archived failure identity.

The private snapshot and imported directory are removed on success and failure. The returned `ArchiveReproReplay` copies the transport digest, validated input bytes, stable failure signature, metadata, replay-context digest, and fresh differential run so its evidence remains usable after temporary cleanup; it exposes the original archive path rather than a stale temporary bundle path.

This API is intentionally a transport/replay interoperability slice. It does not weaken `import_repro_archive`, bypass `load_repro_bundle`, create a remote artifact store, or retain temporary extraction trees.
