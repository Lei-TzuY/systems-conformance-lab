# Durable publish file-sync crash recovery

`DurablePublishFileSyncCrashTarget` validates the pre-replace half of the real durable-file publication protocol.

On platforms with directory `fsync`, the target starts from a synchronized published generation, launches a fixed-argv child writer, writes and file-syncs a new staging generation, waits for a deterministic readiness marker, and then force-kills that writer before `os.replace`. A fresh observer must still see the old published generation while the synchronized staging payload remains intact.

The same target then injects a deterministic `EIO` at the publisher's file-sync checkpoint. The failure must occur before replacement: the published destination remains unchanged and the staging file remains available for diagnosis or cleanup. A subsequent fault-free `FaultingDurableFilePublisher.publish` must still complete the full file-sync, replace, and directory-sync protocol and publish a later generation.

The public command target accepts no input. It uses fixed argv, `shell=False`, detached stdin, captured output, a bounded harness timeout, and deterministic marker-before-kill synchronization. Windows reports the capability as unsupported because the repository's durable-publish contract requires real directory `fsync`; it does not substitute a simulated durability claim.

This contract demonstrates process-loss behavior around the file-sync/pre-replace boundary and deterministic injected file-sync failure. It does not claim power-loss durability, storage-controller persistence, or cross-filesystem rename semantics.
