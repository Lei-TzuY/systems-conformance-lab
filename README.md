# systems-conformance-lab

A reusable systems-correctness laboratory for conformance testing, differential execution, fuzzing, fault injection, reduction, and reproducibility.

The project is intentionally building the correctness substrate first. The current foundation is a safe argv-based process runner plus a structured candidate/oracle comparator that keeps infrastructure failures distinct from product mismatches.

## Current foundation

- argv-only process execution (`shell=False`)
- deterministic UTF-8/stdin byte input handling
- timeout classification and process-tree cleanup
- bounded stdout/stderr capture
- exit-code / signal metadata
- JSON-serializable versioned execution records
- deterministic candidate/oracle comparison
- explicit `match`, `product_mismatch`, and `infrastructure_failure` classification
- truncated-stream metadata comparison to avoid false equivalence
- focused self-tests

## Development

```bash
python -m pip install -e '.[dev]'
pytest
ruff check .
```

The core runner and comparator are deliberately target-independent. Project-specific adapters belong above them rather than inside process execution or comparison semantics.
