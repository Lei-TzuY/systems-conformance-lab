# systems-conformance-lab

A reusable systems-correctness laboratory for conformance testing, differential execution, fuzzing, fault injection, reduction, and reproducibility.

The project is intentionally building the correctness substrate first. The current foundation is a safe argv-based process runner, a structured candidate/oracle comparator, stable failure signatures, a deterministic generic reducer loop, deterministic repro bundles, safe bundle-retention primitives, a bounded deterministic fuzz campaign driver, and a deterministic fault-injection controller that keeps system-specific fault behavior outside the core.

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
- deterministic repro bundles with byte-for-byte input preservation
- safe repro retention that only removes recognized direct-child bundles and never follows symlinks
- deterministic index-driven fuzz case scheduling with a strict evaluation budget
- first-failure capture that preserves product-vs-infrastructure classification
- fuzz case generation/evaluator exceptions remain visible as harness failures
- immutable fault specifications with explicit logical operation, occurrence, and kind
- deterministic single-shot fault checkpoints that count only matching operations
- fault controllers report trigger intent only; target-specific adapters own side effects and failure mapping
- focused self-tests

## Development

```bash
python -m pip install -e '.[dev]'
pytest
ruff check .
```

The core runner, comparator, failure signatures, reducer, repro writer, retention policy, fuzz campaign driver, and fault controller are deliberately target-independent. Project-specific adapters, format-aware generators, mutators, corpora, and concrete fault behaviors belong above them rather than inside the shared correctness substrate.
