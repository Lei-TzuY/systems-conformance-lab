# Portable repro archive retention

`enforce_repro_archive_retention` applies bounded retention directly to transported repro ZIPs without trusting filenames or extensions as evidence of validity.

Only direct-child regular files that successfully traverse the canonical `import_repro_archive` validator are eligible. That validation enforces the archive byte budget, exact member set, regular uncompressed members, bounded input/manifest sizes, and the normal repro bundle schema and digest checks. Directories, symlinks, unrelated files, malformed archives, and tampered bundles are reported as `ignored` and are never intentionally deleted.

Eligible archives are ordered newest-first by file mtime, with filename as a deterministic tie breaker. At most `max_archives` are retained; older eligible archives are unlinked. A path replaced by a symlink after validation is unlinked as a link rather than traversed.

The API returns `ArchiveRetentionResult(kept, removed, ignored)` so callers can record retention evidence. Retained archives remain compatible with `replay_repro_archive`, including transport SHA-256 pinning, replay-context checks, and the optional exact failure-reproduction gate.

This capability intentionally does not recurse, infer validity from `.zip` suffixes, delete malformed evidence, or execute candidate/oracle targets while deciding retention eligibility.
