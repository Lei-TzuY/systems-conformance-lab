# Repro archive export snapshots

`export_repro_archive` never archives a second unvalidated read of a mutable source bundle.

Export first validates the source through `load_repro_bundle`, preserving the bounded validated `input.bin` bytes. It then reads `manifest.json` through the configured manifest-byte ceiling, writes those two artifacts into a private temporary snapshot, and validates that snapshot through the same canonical loader before any ZIP is published. The archive is written only from the validated snapshot.

This keeps the transport invariant precise even when the source directory changes during export: emitted `input.bin` and `manifest.json` bytes have been validated together under the normal replay contract. A source mutation that cannot form a valid snapshot fails export; a mutation after the initial input load cannot silently replace the validated input bytes in the archive.

The archive remains deterministic: members are exactly `input.bin` and `manifest.json`, use `ZIP_STORED`, and carry fixed metadata.

`export_repro_archive` provides atomic no-clobber publication after the complete ZIP is closed. `export_durable_repro_archive` adds an explicit persistence protocol on platforms with portable directory `fsync`: the closed staging ZIP is file-synced, hard-linked into place without replacing an existing destination, then the containing directory is synced. Optional `FaultSpec` values inject deterministic `EIO` at the file-sync or directory-sync boundary. A file-sync fault occurs before publication and leaves no destination. A directory-sync fault occurs after publication, so the complete archive remains visible and replayable but metadata durability is intentionally not claimed. Windows fails closed before publication because this project does not pretend to offer portable directory-fsync semantics there.

On import, destination collision checks treat symbolic links as existing filesystem entries even when their targets do not exist. The destination is checked both before staging begins and again after staged bundle validation, so a dangling symlink already present at the requested publication path—or one that appears while validation is in progress—is rejected rather than intentionally replaced. Failed publication cleans the private staging directory.
