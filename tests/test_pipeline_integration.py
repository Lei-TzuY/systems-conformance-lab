import json
import sys

from systems_conformance import (
    CommandTarget,
    DifferentialHarness,
    failure_signature,
    reduce_case,
    run_fuzz_campaign,
)
from systems_conformance.byte_reducer import hierarchical_byte_deletions

ECHO_SCRIPT = (
    "import sys; data = sys.stdin.buffer.read(); sys.stdout.buffer.write(data)"
)
BUGGY_SCRIPT = (
    "import sys; data = sys.stdin.buffer.read(); "
    "sys.stdout.buffer.write(data.replace(b'BUG', b'BAD') if b'BUG' in data else data)"
)


def target(script: str) -> CommandTarget:
    return CommandTarget((sys.executable, "-c", script))


def test_real_target_pipeline_finds_reduces_and_persists_failure(tmp_path) -> None:
    harness = DifferentialHarness(candidate=target(BUGGY_SCRIPT), oracle=target(ECHO_SCRIPT))
    corpus = (b"ordinary input", b"prefix BUG suffix")

    campaign = run_fuzz_campaign(
        cases=corpus.__getitem__,
        evaluate=harness.compare,
        max_evaluations=len(corpus),
    )

    assert campaign.evaluations == 2
    assert campaign.classification == "product_mismatch"
    assert campaign.failing_case == b"prefix BUG suffix"
    assert campaign.comparison is not None

    signature = failure_signature(campaign.comparison)
    assert signature is not None
    assert signature.dimensions == ("stdout",)

    reduction = reduce_case(
        campaign.failing_case,
        candidates=hierarchical_byte_deletions,
        preserves_failure=lambda case: harness.preserves_failure(case, signature),
        measure=len,
        max_evaluations=100,
    )

    assert reduction.reduced == b"BUG"
    assert reduction.accepted_steps > 0
    assert reduction.evaluations < 40

    bundle = harness.write_repro(
        tmp_path / "repro",
        input_bytes=reduction.reduced,
        expected_signature=signature,
        metadata={"source": "end-to-end-integration"},
    )

    assert bundle.input_path.read_bytes() == b"BUG"
    manifest = json.loads(bundle.manifest_path.read_text(encoding="utf-8"))
    assert manifest["failure_signature"]["kind"] == signature.kind
    assert tuple(manifest["failure_signature"]["dimensions"]) == signature.dimensions
    assert manifest["failure_signature"]["schema_version"] == signature.schema_version
    assert manifest["comparison"]["classification"] == "product_mismatch"
    assert manifest["metadata"] == {"source": "end-to-end-integration"}
