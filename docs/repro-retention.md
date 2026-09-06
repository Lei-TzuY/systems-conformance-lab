# Repro retention safety

`enforce_repro_retention` applies a deterministic count limit only to direct-child repro bundle directories that pass the same canonical bounded validation used by replay.

A bundle is deletion-eligible only when `load_repro_bundle` accepts it. That means retention inherits the v1 exact-member and strict JSON/schema checks, input size and SHA-256 binding, typed execution/comparison/failure evidence validation, and semantic consistency checks. Bundles with same-size input tampering, unexpected members, schema drift, contradictory evidence, symlinked artifacts, or other replay-invalid state are ignored rather than deleted.

Eligible bundles are ordered newest-first by `manifest.json` mtime with directory name as the stable tiebreaker. Retention never follows a symlinked direct child. This keeps garbage collection conservative: unknown or damaged evidence remains available for manual inspection instead of being destroyed merely because it resembles a repro bundle.
