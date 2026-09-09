# File sync fault adapter

`FaultingFileSync` is a concrete durability-boundary fault adapter layered on the generic `FaultSpec` / `FaultController` trigger contract. It executes a real `os.fsync()` against a caller-owned binary file and can inject one deterministic `EIO` at a selected logical fsync occurrence.

The supported contract is intentionally narrow:

- `operation="fsync"`
- `kind="io_error"`
- zero-based `occurrence`

Each `sync()` first flushes the Python stream buffer. If the configured occurrence fires, the adapter raises `OSError(errno.EIO, ...)` before calling `os.fsync`; otherwise it invokes the platform fsync primitive on the stream's file descriptor. After the one-shot injected failure, later `sync()` calls again execute real fsync.

The adapter does not close the file, emulate crash recovery, claim that a filesystem persisted particular metadata, or synthesize durability guarantees stronger than the host OS provides. Those semantics remain target-specific. Its purpose is to give target integrations a deterministic, reproducible durability checkpoint with a real filesystem validation path rather than a fake fault flag.
