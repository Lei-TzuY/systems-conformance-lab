import sys

import pytest

import systems_conformance.repro_archive as repro_archive_module
from systems_conformance import (
    CommandTarget,
    DifferentialHarness,
    export_repro_archive,
    import_repro_archive,
)

ECHO_SCRIPT = "import sys; sys.stdout.buffer.write(sys.stdin.buffer.read())"
BUGGY_SCRIPT = (
    "import sys; data = sys.stdin.buffer.read(); "
    "sys.stdout.buffer.write(data.replace(b'BUG', b'BAD') if b'BUG' in data else data)"
)


def target(script: str) -> CommandTarget:
    return CommandTarget((sys.executable, "-c", script))


def make_archive(tmp_path):
    harness = DifferentialHarness(candidate=target(BUGGY_SCRIPT), oracle=target(ECHO_SCRIPT))
    repro = harness.write_repro(
        tmp_path / "original",
        input_bytes=b"BUG-symlink-destination",
        metadata={"source": "symlink-destination-integration"},
    )
    archive = export_repro_archive(repro.path, tmp_path / "repro.zip")
    return harness, archive


def create_dangling_symlink_or_skip(path) -> None:
    try:
        path.symlink_to(path.parent / "missing-target", target_is_directory=True)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"symlink creation unavailable: {exc}")


def test_import_rejects_existing_dangling_symlink_destination(tmp_path) -> None:
    harness, archive = make_archive(tmp_path)
    destination = tmp_path / "imported"
    create_dangling_symlink_or_skip(destination)

    with pytest.raises(FileExistsError, match="destination already exists"):
        import_repro_archive(archive, destination)

    assert destination.is_symlink()
    assert not (tmp_path / "missing-target").exists()
    replay = harness.replay_repro(tmp_path / "original")
    assert replay.reproduced


def test_import_rechecks_dangling_symlink_before_publication(tmp_path, monkeypatch) -> None:
    harness, archive = make_archive(tmp_path)
    destination = tmp_path / "imported"
    real_loader = repro_archive_module.load_repro_bundle
    calls = 0

    def load_then_claim_destination(path, **kwargs):
        nonlocal calls
        loaded = real_loader(path, **kwargs)
        calls += 1
        if calls == 1:
            create_dangling_symlink_or_skip(destination)
        return loaded

    monkeypatch.setattr(repro_archive_module, "load_repro_bundle", load_then_claim_destination)

    with pytest.raises(FileExistsError, match="destination already exists"):
        import_repro_archive(archive, destination)

    assert destination.is_symlink()
    assert not list(tmp_path.glob(".imported.import-*"))
    replay = harness.replay_repro(tmp_path / "original")
    assert replay.reproduced
