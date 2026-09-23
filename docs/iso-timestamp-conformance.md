# ISO timestamp interoperability

This adapter pair exercises one explicit-offset timestamp parsing boundary through real
Python and Node child processes.

## Semantic contract

Input is raw stdin bytes. The adapter accepts ASCII timestamp text and requires an
explicit UTC marker or numeric offset. Successful parses are projected onto two stable
observables:

- signed Unix epoch milliseconds;
- a UTC ISO string with exactly millisecond precision.

The projection intentionally avoids local-time interpretation. Inputs that parse as
timezone-naive values are reported as `timezone_required` instead of depending on the
host timezone.

## Runtime implementations

- Python uses `datetime.datetime.fromisoformat`.
- Node uses `Date.parse` and `Date.prototype.toISOString`.

Python implementation/version and Node/V8 versions are captured before execution,
verified by the worker, and therefore participate in the existing replay-context hash.

## Executable evidence

The shared subset covers:

- `Z` and numeric offsets;
- compact and colonized offsets;
- valid leap-day timestamps;
- minute-precision input;
- fractional seconds beyond millisecond precision;
- negative Unix time.

The adapters preserve native parser policy instead of normalizing it away. Current
deterministic mismatch evidence includes:

- Node accepts `24:00:00Z` and rolls it into the next day while Python rejects it;
- Node normalizes some out-of-range calendar days that Python rejects;
- Python accepts UTC offsets containing seconds while Node rejects them.

A bounded discovery campaign publishes the `24:00:00Z` mismatch as a normal
context-bound repro and replay must preserve the same stable failure signature.

## Out of scope

This slice does not claim full RFC 3339 equivalence, locale-aware parsing, timezone
database behavior, DST transitions, leap-second support, calendar arithmetic, duration
parsing, or sub-millisecond cross-runtime identity. Those are separate semantic
surfaces.
