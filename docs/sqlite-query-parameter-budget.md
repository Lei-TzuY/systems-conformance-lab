# SQLite query parameter budget

`SQLiteQueryTarget.max_params` bounds the number of positional query parameters accepted by one query request. The default ceiling is 999 parameters.

The bounded worker applies the ceiling after strict protocol decoding and scalar validation but before SQLite executes the query. An input containing more than the configured ceiling is rejected deterministically with exit code 2 and `protocol_error: params exceeds max_params: N`.

The exact boundary is accepted. The ceiling is encoded in the target argv, so changing it changes the harness replay-context fingerprint and prevents replay under a different bind-cardinality contract.

This limit complements the stdin byte budget, SQL byte ceiling, JSON depth ceiling, deterministic VM-step budget, wall-clock timeout, and result/output budgets. It prevents many individually tiny scalar parameters from turning one bounded request into excessive SQLite bind orchestration work.
