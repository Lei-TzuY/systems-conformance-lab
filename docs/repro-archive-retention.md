# Portable repro archive retention

`enforce_repro_archive_retention` applies bounded retention directly to transported repro ZIPs without trusting filenames or extensions as evidence of validity.

Only direct-child regular files that successfully traverse the canonical `import_repro_archive` validator are eligible. That validation enforces the per-archive byte budget, exact member set, regular uncompressed members, bounded input/manifest sizes, and the normal repro bundle schema and digest checks. Directories, symlinks, unrelated files, malformed archives, and tampered bundles are reported as `ignored` and are never intentionally deleted.

Eligible archives are ordered newest-first by file mtime, with filename as a deterministic tie breaker. At most `max_archives` are retained. Callers may also set `max_total_archive_bytes` to bound aggregate retained transport storage. The aggregate budget is applied greedily in newest-first order: an eligible archive that would exceed the remaining byte budget is removed, while a later smaller archive may still be retained if it fits. `None` preserves the count-only behavior. Both limits accept zero and reject booleans, negative values, and other invalid types before directory scanning.

Archive sizes used for retention accounting come from the regular-file metadata captured for each candidate before canonical validation. Every retained item has still passed the normal bounded archive importer; the aggregate limit is a storage-retention policy, not a replacement for archive validation. A path replaced by a symlink after validation is unlinked as a link rather than traversed.

The API returns `ArchiveRetentionResult(kept, removed, ignored)` so callers can record retention evidence. Retained archives remain compatible with `replay_repro_archive`, including transport SHA-256 pinning, replay-context checks, and the optional exact failure-reproduction gate. Integration coverage creates real candidate/oracle repros with different archive sizes, applies the aggregate budget, and replays every retained transport artifact through real child processes.

This capability intentionally does not recurse, infer validity from `.zip` suffixes, delete malformed evidence, or execute candidate/oracle targets while deciding retention eligibility.
