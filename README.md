# systems-conformance-lab

A reusable systems-correctness laboratory for conformance testing, differential execution, fuzzing, fault injection, reduction, and reproducibility.

## Current checkpoint

The repository now has a bounded, target-independent correctness substrate plus one explicit integration boundary for real process targets. The core primitives remain independently usable, while `DifferentialHarness` composes target execution, comparison, stable failure identity, signature-preserving reduction predicates, and repro publication without absorbing target-specific generators or fault side effects.

The stability boundary and deferred scope are documented in [`docs/stability-checkpoint.md`](docs/stability-checkpoint.md).

### Core substrate

- argv-only process execution (`shell=False`)
- deterministic UTF-8/stdin byte input handling
- timeout classification and process-tree cleanup
- bounded stdout/stderr capture with total-size/truncation metadata
- exit-code / signal / infrastructure-error metadata
- JSON-serializable versioned execution records
- deterministic candidate/oracle comparison
- explicit `match`, `product_mismatch`, and `infrastructure_failure` classification
- stable failure signatures for reducer/reproducer identity
- deterministic first-improvement reduction with strict size progress and bounded evaluations
- deterministic repro bundles with byte-for-byte input preservation
- safe repro retention that only removes recognized direct-child bundles and never follows symlinks
- deterministic index-driven fuzz scheduling with a strict evaluation budget
- immutable fault specifications and deterministic single-shot logical-operation checkpoints
- target-specific fault effects kept outside the generic controller

### Integrated execution boundary

`CommandTarget` snapshots one real process target configuration. `DifferentialHarness` then provides the shared execution path:

```text
input bytes
    |
    +--> candidate CommandTarget --> run_process --+
    |                                             |
    +--> oracle CommandTarget ----> run_process --+--> compare_results
                                                       |
                                                       +--> FailureSignature
                                                       |
                                                       +--> fuzz evaluate callback
                                                       +--> reducer preserves-failure predicate
                                                       +--> deterministic repro bundle
```

The integration tests execute actual Python child processes rather than synthetic `ExecutionResult` fixtures. One end-to-end regression drives a deterministic fuzz campaign to a real candidate/oracle mismatch, reduces the failing input while preserving the exact failure signature, and persists the minimized reproducer bundle.

## Minimal usage

```python
import sys

from systems_conformance import CommandTarget, DifferentialHarness

candidate = CommandTarget((sys.executable, "candidate.py"))
oracle = CommandTarget((sys.executable, "oracle.py"))
harness = DifferentialHarness(candidate=candidate, oracle=oracle)

result = harness.evaluate(b"test input\n")
print(result.comparison.classification)
print(result.signature)
```

`harness.compare` can be passed directly to `run_fuzz_campaign`. `harness.preserves_failure` is intended for reducers after a failure signature has been captured. `harness.write_repro` re-evaluates the minimized case and optionally rejects signature drift before publishing evidence.

## Responsibility boundary

The shared package owns correctness mechanics, not product semantics. Format-aware generators, mutators, corpora, normalization rules, concrete fault side effects, protocol/filesystem/compiler knowledge, and target lifecycle orchestration belong in adapters above this package. The generic fault controller reports deterministic trigger intent only; it deliberately does not kill processes, corrupt files, drop packets, or mutate target state itself.

This checkpoint does **not** add a new conformance domain, distributed scheduler, coverage-guided fuzzer, symbolic executor, target-specific mutation engine, or fault backend. Those are separate architecture phases and should only be introduced when a concrete repository integration requires them.

## Development

```bash
python -m pip install -e '.[dev]'
pytest
ruff check .
```
