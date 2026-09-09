# Atomic replace fault adapter

`FaultingAtomicReplace` binds the deterministic fault controller to the host filesystem's real pathname publication primitive, `os.replace`.

The adapter accepts only `FaultSpec(operation="replace", kind="io_error")`. Matching occurrences are zero-based. At the configured occurrence it raises `OSError(EIO)` before publication, leaving both the existing destination and source pathname untouched. Earlier and later occurrences delegate directly to `os.replace`, so successful publication retains the platform's replace semantics.

This boundary is intentionally narrower than a complete crash-consistent file-update protocol. Callers remain responsible for writing and syncing the source before publication and for directory-sync or other durability policy after publication. Keeping those phases separate makes a failure at the publication boundary deterministic and independently reproducible instead of pretending that a successful rename alone proves crash durability.

The integration test uses real files and verifies all three observable states: a successful first publication consumes the source, the injected occurrence preserves the previous destination and the unconsumed source, and a later publication recovers through the real filesystem operation.
