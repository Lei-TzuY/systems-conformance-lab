import os
import sys

import pytest

import systems_conformance.repro_archive as repro_archive_module
from systems_conformance import CommandTarget, DifferentialHarness, export_repro_archive

ECHO_SCRIPT = "import sys; sys.stdout.buffer.write(sys.stdin.buffer.read())"
BUGGY_SCRIPT = (
    "import sys; data = sys.stdin.buffer.read(); "
    "sys.stdout.buffer.write(data.replace(b'BUG', b'BAD') if b'BUG' in data else data)"
)


def target(script: str) -> CommandTarget:
    return CommandTarget((sys.executable, "-c", script))


@pytest.mark.skipif(os.name != "posix", reason="POSIX permits replacing an open staging pathname")
def test_export_rejects_staging_path_replacement_before_publication(
    tmp_path, monkeypatch
) -> None:
    harness = DifferentialHarness(candidate=target(BUGGY_SCRIPT), oracle=target(ECHO_SCRIPT))
    original = harness.write_repro(
        tmp_path / "original",
        input_bytes=b"BUG-staging-identity",
        metadata={"source": "staging-identity-integration"},
    )
    destination = tmp_path / "published.zip"
    real_publish = repro_archive_module._publish_file_no_replace
    replaced = False

    def replace_then_publish(staging_path, archive_path, *, expected):
        nonlocal replaced
        replaced = True
        staging_path.unlink()
        staging_path.write_bytes(b"attacker-controlled replacement")
        return real_publish(staging_path, archive_path, expected=expected)

    monkeypatch.setattr(
        repro_archive_module,
        "_publish_file_no_replace",
        replace_then_publish,
    )

    with pytest.raises(ValueError, match="staging path changed before publication"):
        export_repro_archive(original.path, destination)

    assert replaced
    assert not destination.exists()
    assert not list(tmp_path.glob(".published.zip.export-*.tmp"))
