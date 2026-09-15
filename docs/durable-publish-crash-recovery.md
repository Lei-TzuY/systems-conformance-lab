# Durable publish crash recovery

`DurablePublishCrashTarget` validates the real filesystem publication boundary implemented by `FaultingDurableFilePublisher`: write and file-`fsync` a staging file, atomically replace the destination, then `fsync` the containing directory.

On POSIX hosts the target starts from a destination whose contents and parent directory have both been synced. It then exercises three bounded checkpoints.

1. A child writes and `fsync`s a new staging file, completes `os.replace`, emits `PRE_DIRSYNC_READY`, and is force-terminated before directory sync. A fresh observer must see the complete new generation and the staging pathname must be absent. This proves process-loss visibility after replacement; it deliberately does **not** claim power-loss durability before the directory entry is synced.
2. `FaultingDurableFilePublisher` performs the file sync and replacement but receives deterministic `EIO` at the real `dir_fsync` checkpoint. The new destination remains visible and the staging pathname is absent, demonstrating the important ambiguous state: publication may be visible even though the durability protocol failed and callers must not treat the operation as durably committed.
3. A fresh child completes the full publisher call, including directory sync, emits `POST_PUBLISH_READY`, and is then force-terminated. A fresh observer must see the complete final generation with no staging pathname.

The public adapter uses a fixed argv `CommandTarget`; it does not interpolate untrusted shell text. Non-empty stdin fails closed. Child processes acknowledge deterministic checkpoints before the parent kills them and are cleaned up on every path.

Windows reports the capability as unsupported because this repository's real `FaultingDirectorySync` contract intentionally does not emulate directory `fsync` there. The target therefore avoids making a fake cross-platform durability claim while still participating deterministically in the harness matrix.

This contract is intentionally bounded. It validates process-crash checkpoints and the host filesystem APIs actually invoked by the publisher; it does not simulate sudden power loss, storage-controller cache behavior, or guarantee stronger filesystem semantics than the host provides.

The adapter reports this boundary in its machine-readable result as
`failure_model="process-kill-same-mount"`, `remount_performed=false`, and
`power_loss_recovery_proven=false`. Consumers must preserve these fields when
presenting the result; a green run is evidence for the stated process-crash
contract only, never an implicit upgrade to reboot or power-loss recovery.
