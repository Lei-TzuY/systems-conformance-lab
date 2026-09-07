# Repro archive export snapshots

`export_repro_archive` never archives a second unvalidated read of a mutable source bundle.

Export first validates the source through `load_repro_bundle`, preserving the bounded validated `input.bin` bytes. It then reads `manifest.json` through the configured manifest-byte ceiling, writes those two artifacts into a private temporary snapshot, and validates that snapshot through the same canonical loader before any ZIP is published. The archive is written only from the validated snapshot.

This keeps the transport invariant precise even when the source directory changes during export: emitted `input.bin` and `manifest.json` bytes have been validated together under the normal replay contract. A source mutation that cannot form a valid snapshot fails export; a mutation after the initial input load cannot silently replace the validated input bytes in the archive.

The archive remains deterministic: members are exactly `input.bin` and `manifest.json`, use `ZIP_STORED`, and carry fixed metadata.
