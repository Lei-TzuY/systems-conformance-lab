# Durable file publisher

`FaultingDurableFilePublisher` composes the concrete durability fault adapters into one
real filesystem update protocol: write a staging file, flush and `fsync` its content,
atomically publish it with `os.replace`, then `fsync` the containing directory.

The three `FaultSpec` values remain independent checkpoints. Injected file-sync or
replace failures leave the previously published destination intact and retain the
staging file. A directory-sync failure happens after pathname publication, so the new
bytes are visible but their metadata durability is intentionally not claimed.

Source and destination must share a parent directory so publication does not silently
cross filesystem boundaries. Directory `fsync` is not portable on Windows, so the
publisher inherits `FaultingDirectorySync`'s fail-closed `NotImplementedError` there.
The adapter models the syscall-level protocol and deterministic failure boundaries; it
does not claim to emulate power-loss persistence behavior of a particular filesystem.
