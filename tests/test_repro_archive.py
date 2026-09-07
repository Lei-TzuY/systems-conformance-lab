import stat
import sys
import zipfile

import pytest

import systems_conformance.repro_archive as repro_archive_module
from systems_conformance import (
    CommandTarget,
    DifferentialHarness,
    export_repro_archive,
    import_repro_archive,
)

ECHO_SCRIPT = (
    "import sys; data = sys.stdin.buffer.read(); sys.stdout.buffer.write(data)"
)
BUGGY_SCRIPT = (
    "import sys; data = sys.stdin.buffer.read(); "
    "sys.stdout.buffer.write(data.replace(b'BUG', b'BAD') if b'BUG' in data else data)"
)


def target(script: str) -> CommandTarget:
    return CommandTarget((sys.executable, "-c", script))


def test_export_is_deterministic_and_import_replays_real_targets(tmp_path) -> None:
    harness = DifferentialHarness(candidate=target(BUGGY_SCRIPT), oracle=target(ECHO_SCRIPT))
    original = harness.write_repro(
        tmp_path / "original",
        input_bytes=b"BUG",
        metadata={"source": "archive-integration"},
    )

    first_archive = export_repro_archive(original.path, tmp_path / "first.zip")
    second_archive = export_repro_archive(original.path, tmp_path / "second.zip")

    assert first_archive.read_bytes() == second_archive.read_bytes()

    imported = import_repro_archive(first_archive, tmp_path / "imported")
    assert imported.input_path.read_bytes() == b"BUG"
    assert imported.manifest_path.read_bytes() == original.manifest_path.read_bytes()

    replay = harness.replay_repro(imported.path)
    assert replay.reproduced
    assert replay.run.signature == replay.bundle.signature
    assert replay.bundle.metadata == {"source": "archive-integration"}


def test_export_archives_validated_snapshot_when_source_changes_after_load(
    tmp_path, monkeypatch
) -> None:
    harness = DifferentialHarness(candidate=target(BUGGY_SCRIPT), oracle=target(ECHO_SCRIPT))
    original = harness.write_repro(
        tmp_path / "original",
        input_bytes=b"BUG",
        metadata={"source": "snapshot-integration"},
    )
    real_loader = repro_archive_module.load_repro_bundle
    calls = 0

    def load_then_mutate(path, **kwargs):
        nonlocal calls
        loaded = real_loader(path, **kwargs)
        calls += 1
        if calls == 1:
            original.input_path.write_bytes(b"BAD")
        return loaded

    monkeypatch.setattr(repro_archive_module, "load_repro_bundle", load_then_mutate)

    archive = export_repro_archive(original.path, tmp_path / "snapshot.zip")
    imported = import_repro_archive(archive, tmp_path / "imported")

    assert original.input_path.read_bytes() == b"BAD"
    assert imported.input_path.read_bytes() == b"BUG"
    replay = harness.replay_repro(imported.path)
    assert replay.reproduced
    assert replay.bundle.metadata == {"source": "snapshot-integration"}


def test_import_rejects_unexpected_member_before_destination_creation(tmp_path) -> None:
    archive_path = tmp_path / "bad.zip"
    with zipfile.ZipFile(archive_path, mode="w", compression=zipfile.ZIP_STORED) as archive:
        archive.writestr("input.bin", b"case")
        archive.writestr("manifest.json", b"{}")
        archive.writestr("../escape", b"nope")

    destination = tmp_path / "imported"
    with pytest.raises(ValueError, match="exactly input.bin and manifest.json"):
        import_repro_archive(archive_path, destination)

    assert not destination.exists()
    assert not (tmp_path.parent / "escape").exists()


def test_import_rejects_explicit_symlink_member_before_destination_creation(tmp_path) -> None:
    archive_path = tmp_path / "symlink.zip"
    symlink = zipfile.ZipInfo("input.bin")
    symlink.compress_type = zipfile.ZIP_STORED
    symlink.create_system = 3
    symlink.external_attr = (stat.S_IFLNK | 0o777) << 16

    with zipfile.ZipFile(archive_path, mode="w", compression=zipfile.ZIP_STORED) as archive:
        archive.writestr(symlink, b"manifest.json")
        archive.writestr("manifest.json", b"{}")

    destination = tmp_path / "imported"
    with pytest.raises(ValueError, match="members must be regular files"):
        import_repro_archive(archive_path, destination)

    assert not destination.exists()


def test_import_rejects_compressed_members_before_destination_creation(tmp_path) -> None:
    archive_path = tmp_path / "compressed.zip"
    with zipfile.ZipFile(archive_path, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("input.bin", b"case")
        archive.writestr("manifest.json", b"{}")

    destination = tmp_path / "imported"
    with pytest.raises(ValueError, match="ZIP_STORED"):
        import_repro_archive(archive_path, destination)

    assert not destination.exists()


def test_import_rejects_invalid_bundle_before_publication(tmp_path) -> None:
    archive_path = tmp_path / "invalid.zip"
    with zipfile.ZipFile(archive_path, mode="w", compression=zipfile.ZIP_STORED) as archive:
        archive.writestr("input.bin", b"case")
        archive.writestr("manifest.json", b"{}")

    destination = tmp_path / "imported"
    with pytest.raises(ValueError, match="fields do not match v1 schema"):
        import_repro_archive(archive_path, destination)

    assert not destination.exists()
    assert not list(tmp_path.glob(".imported.import-*"))
