# systems-conformance-lab

A reusable systems-correctness laboratory for conformance testing, differential execution, fuzzing, fault injection, reduction, and reproducibility.

## Current checkpoint

The repository now has a bounded, target-independent correctness substrate plus one explicit integration boundary for real process targets. The core primitives remain independently usable, while `DifferentialHarness` composes target execution, comparison, stable failure identity, signature-preserving reduction predicates, repro publication, and safe repro replay without absorbing target-specific generators or fault side effects.

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
- SHA-256 input-content binding for newly written repros, with legacy v1 digestless replay compatibility
- safe repro retention that only removes recognized direct-child bundles and never follows symlinks
- bounded repro loading that validates schema, direct-child layout, artifact sizes, input digests when present, and stable failure identity before replay
- non-disclosing SHA-256 replay-context binding for harness-written repros, covering candidate/oracle configuration plus timeout/output limits
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
                                                       +--> validated, context-bound repro replay
```

The integration tests execute actual Python child processes rather than synthetic `ExecutionResult` fixtures. One end-to-end regression drives a deterministic fuzz campaign to a real candidate/oracle mismatch, reduces the failing input while preserving the exact failure signature, and persists the minimized reproducer bundle. Replay tests then reload persisted evidence through the bounded loader and verify the same real-process failure identity. Newly written bundles bind `input.bin` to the manifest with SHA-256 so same-size input corruption is rejected before a target executes, while older v1 bundles without that additive field remain replayable. Harness-written bundles also carry a SHA-256 fingerprint of execution-affecting target settings, allowing replay to reject an accidentally different target context before untrusted input executes. The fingerprint does not persist raw argv, cwd, or environment values.

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

`harness.compare` can be passed directly to `run_fuzz_campaign`. `harness.preserves_failure` is intended for reducers after a failure signature has been captured. `harness.write_repro` re-evaluates the minimized case and optionally rejects signature drift before publishing evidence. `harness.replay_repro` first validates the persisted bundle, checks the replay-context fingerprint by default, and then reports whether a fresh real-process execution preserves its stable failure signature. Set `require_same_context=False` only when intentionally testing evidence against a changed target configuration.

## Responsibility boundary

The shared package owns correctness mechanics, not product semantics. Format-aware generators, mutators, corpora, normalization rules, concrete fault side effects, protocol/filesystem/compiler knowledge, and target lifecycle orchestration belong in adapters above this package. The generic fault controller reports deterministic trigger intent only; it deliberately does not kill processes, corrupt files, drop packets, or mutate target state itself.

This checkpoint does **not** add a new conformance domain, distributed scheduler, coverage-guided fuzzer, symbolic executor, target-specific mutation engine, or fault backend. Those are separate architecture phases and should only be introduced when a concrete repository integration requires them.

## Development

```bash
python -m pip install -e '.[dev]'
pytest
ruff check .
```
