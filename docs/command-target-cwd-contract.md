# Command target working-directory contract

`CommandTarget` treats the effective working directory as execution-affecting replay configuration.

An absolute explicit `cwd` is stored as an absolute path. A relative explicit `cwd` is anchored against the Python process working directory at `CommandTarget` construction time and stored as that absolute path. Later calls to `os.chdir()` therefore cannot redirect an already-constructed target while leaving its replay-context fingerprint unchanged.

`cwd=None` remains visible on the public configuration to mean that no explicit directory was supplied, but the target snapshots the construction-time working directory for execution and replay identity. This gives implicit targets the same reproducibility guarantee: a later ambient `os.chdir()` cannot silently move the real child process while preserving the original replay fingerprint.

Anchoring is lexical rather than a filesystem canonicalization step: explicit relative paths are not symlink-resolved and are not required to exist at construction time. Normal process-spawn handling remains responsible for reporting a missing or inaccessible explicit directory as a structured infrastructure failure.