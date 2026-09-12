# SQLite WAL reader admission after committed writer crash

`SQLiteWALPostCrashReaderAdmissionTarget` validates reader admission and incremental checkpoint retention after a writer process dies **after** crossing a successful WAL commit boundary.

The target uses a real temporary file-backed WAL database. An older reader pins snapshot `70`; a writer commits `71`; then an independent writer process commits `72`, emits a fixed post-commit readiness marker, and is force-killed. The surviving older reader must still see `70`, while a fresh observer must see durable value `72` and checkpoint truncation must remain blocked by the older snapshot.

A new independent reader is then admitted after the writer crash and pins snapshot `72`. A fresh writer commits `73`. The old reader must continue to see `70`, the post-crash reader must continue to see `72`, and checkpoint truncation must remain busy. Releasing the older reader must not over-release the newer reader's retention state: the post-crash reader must still observe `72` and keep the checkpoint busy while a fresh observer sees `73`.

Only after the post-crash reader is also force-released may the truncating checkpoint become non-busy. A fresh reopen must see durable `73` with `PRAGMA integrity_check = ok`; a follow-up commit to `74` must also survive another reopen with integrity intact and a non-busy checkpoint.

The outer target rejects non-empty test-program input before database work. Child processes use fixed argv-only module invocation with `shell=False`; time and output remain bounded by the normal `CommandTarget` runner. The JSON transcript contains stable semantic observations rather than process IDs, WAL frame counts, or platform-specific exit codes.

This slice proves that committed-writer death does not prevent later reader admission and does not corrupt independent snapshot ownership or incremental checkpoint reclamation. It does not claim power-loss durability, torn-write recovery, storage-controller cache persistence, or byte-identical WAL layout.
