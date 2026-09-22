import os
import sys
from pathlib import Path

import pytest

from systems_conformance import (
    CommandTarget,
    DifferentialHarness,
    export_repro_archive,
    import_repro_archive,
    repro_archive as repro_archive_module,
)


pytestmark = pytest.mark.skipif(
    os.name != "posix" or not getattr(os, "O_NOFOLLOW", 0),
    reason="platform does not provide POSIX O_NOFOLLOW semantics",
)


def _target(script: str) -> CommandTarget:
    return CommandTarget((sys.executable, "-c", script))


def test_bounded_snapshot_opens_final_component_without_following_symlinks(
    tmp_path, monkeypatch
) -> None:
    source = tmp_path / "source.bin"
    source.write_bytes(b"bounded")
    real_open = repro_archive_module.os.open
    observed_flags = []

    def observing_open(path, flags, *args, **kwargs):
        observed_flags.append(flags)
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(repro_archive_module.os, "open", observing_open)

    assert repro_archive_module._read_bounded_bytes(
        source, max_bytes=32, label="test input"
    ) == b"bounded"
    assert observed_flags
    assert observed_flags[0] & os.O_NOFOLLOW


def test_import_rejects_symlink_swap_to_same_valid_archive_inode(
    tmp_path, monkeypatch
) -> None:
    echo = "import sys; data=sys.stdin.buffer.read(); sys.stdout.buffer.write(data)"
    buggy = (
        "import sys; data=sys.stdin.buffer.read(); "
        "sys.stdout.buffer.write(data.replace(b'BUG', b'BAD'))"
    )
    harness = DifferentialHarness(candidate=_target(buggy), oracle=_target(echo))
    bundle = harness.write_repro(
        tmp_path / "bundle",
        input_bytes=b"BUG",
        metadata={"source": "nofollow-race-integration"},
    )
    archive = export_repro_archive(bundle.path, tmp_path / "portable.zip")
    backing = tmp_path / "portable-backing.zip"
    destination = tmp_path / "imported"
    real_open = repro_archive_module.os.open
    swapped = False

    def racing_open(path, flags, *args, **kwargs):
        nonlocal swapped
        if Path(path) == archive and not swapped:
            swapped = True
            archive.rename(backing)
            archive.symlink_to(backing.name)
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(repro_archive_module.os, "open", racing_open)

    with pytest.raises(ValueError, match="could not be opened as validated"):
        import_repro_archive(archive, destination)

    assert swapped
    assert archive.is_symlink()
    assert backing.is_file()
    assert not destination.exists()
    assert not list(tmp_path.glob(".imported.import-*"))
