# Command target working-directory contract

`CommandTarget` treats an explicit working directory as execution-affecting replay configuration.

An absolute `cwd` is stored as an absolute path. A relative `cwd` is anchored against the Python process working directory at `CommandTarget` construction time and stored as that absolute path. Later calls to `os.chdir()` therefore cannot redirect an already-constructed target while leaving its replay-context fingerprint unchanged.

`cwd=None` deliberately retains the process-runner inheritance contract. Callers that require a working directory to be reproducible independently of ambient process state should provide `cwd` explicitly.

Anchoring is lexical rather than a filesystem canonicalization step: it does not resolve symlinks or require the target directory to exist at construction time. Normal process-spawn handling remains responsible for reporting a missing or inaccessible directory as a structured infrastructure failure.