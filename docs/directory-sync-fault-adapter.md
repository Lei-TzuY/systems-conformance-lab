# Directory sync fault adapter

`FaultingDirectorySync` connects the deterministic `FaultSpec` / `FaultController`
substrate to a real directory durability boundary.

The adapter accepts only `operation="dir_fsync"` with `kind="io_error"`. Successful
occurrences open the requested directory and call the host `fsync` primitive on its
file descriptor. The selected fault occurrence raises `OSError(EIO)` before opening
or syncing the directory; later occurrences resume the real sync path.

This adapter deliberately models directory metadata durability separately from file
content durability and atomic pathname publication. A durable update protocol may
therefore compose `FaultingFileSync`, `FaultingAtomicReplace`, and
`FaultingDirectorySync` at distinct checkpoints instead of treating rename success as
proof that the containing directory reached stable storage.

Directory `fsync` is not a portable Windows primitive. Construction fails closed with
`NotImplementedError` on Windows rather than silently pretending to provide a
durability checkpoint. POSIX integration tests exercise a real temporary directory.
