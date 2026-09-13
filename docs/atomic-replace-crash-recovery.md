# Atomic replace crash recovery

`AtomicReplaceCrashTarget` validates one bounded real-filesystem publication lifecycle around `os.replace` and the existing deterministic `FaultingAtomicReplace` adapter.

The target starts with a synced destination containing `generation-0`. A fresh child process writes and `fsync`s a `generation-1` staging file, emits `PRE_REPLACE_READY`, and is force-terminated only after that acknowledgement, before any replace call. A fresh observer must still read the complete old destination while the staged new generation remains separately present. This establishes the pre-publication process-crash boundary.

A second fresh child writes and `fsync`s `generation-2`, calls `os.replace(staging, destination)`, emits `POST_REPLACE_READY` only after the replacement returns successfully, and is then force-terminated. A fresh observer must read exactly the complete `generation-2` destination and the staging pathname must be absent. This establishes the post-publication process-crash boundary without depending on process IDs, temporary paths, or platform-specific termination codes.

The target then writes and syncs `generation-3` into another staging file and invokes `FaultingAtomicReplace` with an `io_error` fault at replace occurrence zero. The injected `EIO` must leave the already-published `generation-2` destination byte-for-byte unchanged and preserve the unpublished staging file. After cleanup, a normal synced `generation-4` staging file is published with a real `os.replace`; the destination must reopen as exactly `generation-4` and that staging pathname must be gone.

All child processes are launched with fixed argv arrays, `shell=False`, disconnected stdin, captured stdout/stderr, and bounded post-kill collection. The public target accepts no test-program input; non-empty stdin fails closed before filesystem work. Its output is a stable semantic JSON transcript, so two independent executions can be compared through `DifferentialHarness`.

This slice validates process-loss behavior around a same-filesystem atomic pathname replacement and deterministic injected replace failure. It does **not** claim power-loss durability, directory-entry persistence after sudden machine failure, storage-controller cache persistence, cross-filesystem rename semantics, filesystem-specific crash consistency beyond a completed `os.replace`, or torn-write protection for unsynced staging data. Those require explicit directory-sync and storage-fault contracts rather than being inferred from process termination.
