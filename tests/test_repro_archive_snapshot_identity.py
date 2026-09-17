import os
import sys

import pytest

import systems_conformance.repro_archive as repro_archive_module
from systems_conformance import (
    CommandTarget,
    DifferentialHarness,
    export_repro_archive,
    import_repro_archive,
)


def test_bounded_snapshot_rejects_regular_file_replacement_before_open(
    tmp_path, monkeypatch
) -> None:
    source = tmp_path / "source.bin"
    replacement = tmp_path / "replacement.bin"
    source.write_bytes(b"trusted")
    replacement.write_bytes(b"replacement")
    real_open = os.open
    swapped = False

    def swapping_open(path, flags, *args, **kwargs):
        nonlocal swapped
        if not swapped and os.fspath(path) == os.fspath(source):
            swapped = True
            os.replace(replacement, source)
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(repro_archive_module.os, "open", swapping_open)

    with pytest.raises(ValueError, match="path changed while being opened"):
        repro_archive_module._read_bounded_bytes(
            source,
            max_bytes=1024,
            label="test snapshot",
        )

    assert swapped


def test_archive_snapshot_identity_keeps_real_target_round_trip(tmp_path) -> None:
    echo = "import sys; data=sys.stdin.buffer.read(); sys.stdout.buffer.write(data)"
    buggy = (
        "import sys; data=sys.stdin.buffer.read(); "
        "sys.stdout.buffer.write(b'BAD' if data == b'BUG' else data)"
    )
    harness = DifferentialHarness(
        candidate=CommandTarget((sys.executable, "-c", buggy)),
        oracle=CommandTarget((sys.executable, "-c", echo)),
    )
    original = harness.write_repro(tmp_path / "original", input_bytes=b"BUG")

    archive = export_repro_archive(original.path, tmp_path / "repro.zip")
    imported = import_repro_archive(archive, tmp_path / "imported")
    replay = harness.replay_repro(imported.path)

    assert replay.reproduced
    assert replay.run.signature == replay.bundle.signature
