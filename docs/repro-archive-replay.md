# Portable repro archive replay

`replay_repro_archive` composes the portable archive boundary with `DifferentialHarness` replay without requiring callers to publish an imported bundle into their retained repro directory.

The archive first traverses `import_repro_archive` inside a private temporary directory. That preserves the existing immutable source snapshot, exact-member, regular-file, `ZIP_STORED`, encryption, size, digest, manifest-schema, and semantic-consistency checks. Only after that import succeeds does the private bundle traverse `DifferentialHarness.replay_repro`.

Replay-context validation therefore still happens before untrusted `input.bin` executes. A context mismatch fails without launching either candidate or oracle. Invalid archives likewise fail during the archive/bundle validation boundary before target execution.

The private imported directory is removed on success and failure. The returned `ArchiveReproReplay` copies the validated input bytes, stable failure signature, metadata, replay-context digest, and fresh differential run so its evidence remains usable after temporary cleanup; it exposes the original archive path rather than a stale temporary bundle path.

This API is intentionally a transport/replay interoperability slice. It does not weaken `import_repro_archive`, bypass `load_repro_bundle`, create a remote artifact store, or retain temporary extraction trees.
