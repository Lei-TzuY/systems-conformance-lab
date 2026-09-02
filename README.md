# systems-conformance-lab

A reusable systems-correctness laboratory for conformance testing, differential execution, fuzzing, fault injection, reduction, and reproducibility.

The project is intentionally building the correctness substrate first. The current foundation is a safe argv-based process runner, a structured candidate/oracle comparator, stable failure signatures, and a deterministic generic reducer loop that keeps infrastructure failures distinct from product mismatches.

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
- stable failure signatures for reducer/reproducer identity
- deterministic first-improvement reduction with strict size progress
- bounded reduction evaluation budget
- reducer predicate exceptions remain visible as harness/infrastructure failures
- focused self-tests

## Development

```bash
python -m pip install -e '.[dev]'
pytest
ruff check .
```

The core runner, comparator, failure signatures, and reducer are deliberately target-independent. Project-specific adapters and format-aware candidate generators belong above them rather than inside the shared correctness substrate.
