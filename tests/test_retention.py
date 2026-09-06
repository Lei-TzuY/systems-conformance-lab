import json
import os

import pytest

from systems_conformance.comparator import compare_results
from systems_conformance.failure import failure_signature
from systems_conformance.model import ExecutionResult, StreamCapture
from systems_conformance.repro import REPRO_BUNDLE_SCHEMA_VERSION, write_repro_bundle
from systems_conformance.retention import enforce_repro_retention

_ONE_SECOND_NS = 1_000_000_000


def _result(stdout: str) -> ExecutionResult:
    encoded = stdout.encode()
    return ExecutionResult(
        argv=("tool",),
        duration_ms=1,
        timed_out=False,
        exit_code=0,
        signal=None,
        stdout=StreamCapture(stdout, len(encoded), False),
        stderr=StreamCapture("", 0, False),
    )


def _bundle(root, name: str, *, mtime_ns: int):
    candidate = _result("candidate")
    oracle = _result("oracle")
    comparison = compare_results(candidate, oracle)
    signature = failure_signature(comparison)
    assert signature is not None
    bundle = write_repro_bundle(
        root / name,
        input_bytes=b"case",
        candidate=candidate,
        oracle=oracle,
        comparison=comparison,
        signature=signature,
    )
    os.utime(bundle.manifest_path, ns=(mtime_ns, mtime_ns))
    return bundle.path


def test_retention_keeps_newest_bundles(tmp_path):
    oldest = _bundle(tmp_path, "oldest", mtime_ns=_ONE_SECOND_NS)
    middle = _bundle(tmp_path, "middle", mtime_ns=2 * _ONE_SECOND_NS)
    newest = _bundle(tmp_path, "newest", mtime_ns=3 * _ONE_SECOND_NS)

    result = enforce_repro_retention(tmp_path, max_bundles=2)

    assert result.kept == (newest, middle)
    assert result.removed == (oldest,)
    assert not oldest.exists()
    assert middle.exists()
    assert newest.exists()


def test_retention_uses_name_as_stable_tiebreaker(tmp_path):
    beta = _bundle(tmp_path, "beta", mtime_ns=10 * _ONE_SECOND_NS)
    alpha = _bundle(tmp_path, "alpha", mtime_ns=10 * _ONE_SECOND_NS)

    result = enforce_repro_retention(tmp_path, max_bundles=1)

    assert result.kept == (alpha,)
    assert result.removed == (beta,)


def test_retention_ignores_unknown_or_malformed_children(tmp_path):
    valid = _bundle(tmp_path, "valid", mtime_ns=_ONE_SECOND_NS)
    unknown = _bundle(tmp_path, "unknown", mtime_ns=2 * _ONE_SECOND_NS)
    unknown_manifest = unknown / "manifest.json"
    manifest = json.loads(unknown_manifest.read_text(encoding="utf-8"))
    manifest["schema_version"] = "future.v2"
    unknown_manifest.write_text(json.dumps(manifest), encoding="utf-8")
    malformed = tmp_path / "malformed"
    malformed.mkdir()
    (malformed / "input.bin").write_bytes(b"case")
    (malformed / "manifest.json").write_text("not-json", encoding="utf-8")
    marker = tmp_path / "marker.txt"
    marker.write_text("keep", encoding="utf-8")

    result = enforce_repro_retention(tmp_path, max_bundles=0)

    assert result.removed == (valid,)
    assert result.ignored == (malformed, marker, unknown)
    assert unknown.exists()
    assert malformed.exists()
    assert marker.read_text(encoding="utf-8") == "keep"


def test_retention_ignores_bundle_with_mismatched_input_size(tmp_path):
    mismatched = _bundle(tmp_path, "mismatched", mtime_ns=_ONE_SECOND_NS)
    manifest_path = mismatched / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["input"]["size_bytes"] = 99
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    result = enforce_repro_retention(tmp_path, max_bundles=0)

    assert result.removed == ()
    assert result.ignored == (mismatched,)
    assert mismatched.exists()


def test_retention_ignores_same_size_input_digest_tampering(tmp_path):
    tampered = _bundle(tmp_path, "tampered", mtime_ns=_ONE_SECOND_NS)
    (tampered / "input.bin").write_bytes(b"CASE")

    result = enforce_repro_retention(tmp_path, max_bundles=0)

    assert result.removed == ()
    assert result.ignored == (tampered,)
    assert tampered.exists()


def test_retention_ignores_bundle_with_unexpected_member(tmp_path):
    tampered = _bundle(tmp_path, "tampered", mtime_ns=_ONE_SECOND_NS)
    (tampered / "notes.txt").write_text("unexpected", encoding="utf-8")

    result = enforce_repro_retention(tmp_path, max_bundles=0)

    assert result.removed == ()
    assert result.ignored == (tampered,)
    assert tampered.exists()


def test_retention_does_not_follow_symlinked_bundle(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    target = _bundle(outside, "target", mtime_ns=_ONE_SECOND_NS)
    root = tmp_path / "root"
    root.mkdir()
    link = root / "linked"
    try:
        link.symlink_to(target, target_is_directory=True)
    except OSError:
        pytest.skip("symlink creation unavailable")

    result = enforce_repro_retention(root, max_bundles=0)

    assert result.removed == ()
    assert result.ignored == (link,)
    assert target.exists()


def test_missing_root_is_a_noop(tmp_path):
    result = enforce_repro_retention(tmp_path / "missing", max_bundles=3)

    assert result.kept == ()
    assert result.removed == ()
    assert result.ignored == ()


def test_invalid_limits_are_rejected(tmp_path):
    with pytest.raises(ValueError):
        enforce_repro_retention(tmp_path, max_bundles=-1)
    with pytest.raises(TypeError):
        enforce_repro_retention(tmp_path, max_bundles=True)


def test_schema_constant_matches_writer_contract():
    assert REPRO_BUNDLE_SCHEMA_VERSION == "systems-conformance.repro-bundle.v1"
