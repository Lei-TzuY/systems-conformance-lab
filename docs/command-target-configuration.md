# Command target configuration contract

`CommandTarget` is the immutable execution boundary used by `DifferentialHarness` and by replay-context fingerprinting. Its `argv` elements and explicit environment keys and values must already be strings. The constructor rejects text/bytes passed as the argv container itself and rejects non-string argv or environment members with `TypeError`; it does not coerce arbitrary Python objects with `str(...)`.

This matches the fail-closed contract enforced by `run_process()`. Rejecting invalid configuration before it becomes a `CommandTarget` prevents a caller object from being silently transformed into different process arguments or environment values and then fingerprinted as though that transformed configuration had been supplied intentionally.

Mutable argv/environment containers are still snapshotted at construction. `env=None` continues to mean inherited environment, while an explicit mapping is sorted into deterministic key order. Validated targets continue through the normal real-process runner, including timeout, byte-budget, process-tree cleanup, and infrastructure-failure classification.
