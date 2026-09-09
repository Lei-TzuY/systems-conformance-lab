# Durable repro archive import

`import_durable_repro_archive` extends the bounded archive importer with an explicit POSIX durability contract. The source archive still passes through the ordinary immutable-snapshot ZIP validation path before any final destination becomes visible.

The durable import then executes these ordered sync checkpoints:

1. fsync the validated staging `input.bin`;
2. fsync the validated staging `manifest.json`;
3. fsync the staging bundle directory so its member entries are durable;
4. atomically publish the complete staging bundle with an OS no-replace directory rename primitive;
5. fsync the destination parent directory so publication metadata is durable.

Publication is race-safe rather than an existence-check convention: Linux uses `renameat2(..., RENAME_NOREPLACE)`, macOS uses `renamex_np(..., RENAME_EXCL)`, and the ordinary non-durable importer uses Windows `MoveFileExW` without replacement. Unsupported platforms fail closed instead of falling back to `os.rename()`. A destination entry created after validation but before publication is preserved and the import fails with `FileExistsError`.

A `FaultSpec(operation="import_sync", occurrence=N, kind="io_error")` injects deterministic `EIO` immediately before sync checkpoint `N`. Occurrences 0 through 2 are pre-publication and therefore leave no destination. Occurrence 3 is the parent-directory sync after publication: the destination is already visible and valid for replay, but the API deliberately does not claim that the publication is durable.

Directory fsync has no portable Windows equivalent used by this project. The durable importer therefore fails closed on Windows before staging or publication instead of silently weakening the guarantee. Use `import_repro_archive` when atomic validated import without this POSIX durability contract is sufficient.
