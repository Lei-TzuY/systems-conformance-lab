import os
import sys

from systems_conformance import CommandTarget, DifferentialHarness
from systems_conformance.retention import enforce_repro_retention

ECHO_SCRIPT = (
    "import sys; data = sys.stdin.buffer.read(); sys.stdout.buffer.write(data)"
)
BUGGY_SCRIPT = (
    "import sys; data = sys.stdin.buffer.read(); "
    "sys.stdout.buffer.write(data.replace(b'BUG', b'BAD'))"
)


def _target(script: str) -> CommandTarget:
    return CommandTarget((sys.executable, "-c", script))


def test_real_harness_retention_ignores_tampered_bundle_but_deletes_valid_one(
    tmp_path,
) -> None:
    harness = DifferentialHarness(
        candidate=_target(BUGGY_SCRIPT),
        oracle=_target(ECHO_SCRIPT),
    )
    valid = harness.write_repro(tmp_path / "valid", input_bytes=b"BUG")
    tampered = harness.write_repro(tmp_path / "tampered", input_bytes=b"BUG")

    os.utime(valid.manifest_path, ns=(1_000_000_000, 1_000_000_000))
    os.utime(tampered.manifest_path, ns=(2_000_000_000, 2_000_000_000))
    tampered.input_path.write_bytes(b"BAG")

    result = enforce_repro_retention(tmp_path, max_bundles=0)

    assert result.removed == (valid.path,)
    assert result.ignored == (tampered.path,)
    assert not valid.path.exists()
    assert tampered.path.exists()
    assert tampered.input_path.read_bytes() == b"BAG"
