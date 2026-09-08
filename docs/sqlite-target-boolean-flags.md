# SQLite target boolean flag contract

`SQLiteQueryTarget` and `SQLiteTransactionTarget` treat execution-affecting switches as typed configuration, not generic truthy/falsy values. `foreign_keys`, `enable_faults`, and transaction `reopen_before_observe` must therefore be actual Python `bool` instances.

The adapters validate these fields before a `CommandTarget` is produced. Values such as `0`, `1`, strings, or `None` are rejected instead of being silently converted into `--foreign-keys`/`--no-foreign-keys`, `--enable-faults`/`--disable-faults`, or reopen-mode argv. This keeps caller configuration mistakes out of the process-isolated execution path and makes execution/replay configuration unambiguous.

Valid `True` and `False` values continue to execute through the real SQLite worker processes. The contract does not coerce configuration supplied by callers.