# systems-conformance-lab

A reusable systems-correctness laboratory for conformance testing, differential execution, fuzzing, fault injection, reduction, and reproducibility.

The project is intentionally building the correctness substrate first. The current foundation is a safe argv-based process runner that emits a versioned structured execution record suitable for later candidate/oracle comparison.

## Current foundation

- argv-only process execution (`shell=False`)
- deterministic UTF-8/stdin byte input handling
- timeout classification
- bounded stdout/stderr capture
- exit-code / signal metadata
- JSON-serializable versioned execution records
- focused self-tests

## Development

```bash
python -m pip install -e '.[dev]'
pytest
ruff check .
```

The core runner is deliberately target-independent. Project-specific adapters belong above it rather than inside process execution.
