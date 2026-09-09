# Process stdin contract

`run_process()` treats stdin as an exact byte payload. Callers must provide `bytes`; text strings, `bytearray`, `memoryview`, `None`, and other objects are rejected with `TypeError` before the target process is launched.

This fail-closed boundary matters because stdin is written from a background thread after process creation. Deferring type failure to that thread could otherwise allow an untrusted target to start and observe EOF or partial input even though the caller supplied an invalid payload, producing a misleading conformance result.

The existing `max_input_bytes` check remains independent: valid byte payloads larger than the configured limit are rejected before launch with `ValueError`, while a payload exactly at the limit is delivered intact.
