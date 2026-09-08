import hashlib
import os
import sys
import zipfile

import pytest

from systems_conformance import (
    CommandTarget,
    DifferentialHarness,
    enforce_repro_archive_retention,
    export_repro_archive,
    replay_repro_archive,
)

ECHO_SCRIPT = "import sys; data=sys.stdin.buffer.read(); sys.stdout.buffer.write(data)"
BUGGY_SCRIPT = (
    "import sys; data=sys.stdin.buffer.read(); "
    "sys.stdout.buffer.write(data.replace(b'BUG', b'BAD') if b'BUG' in data else data)"
)
EXIT_SCRIPT = "import sys; sys.stdin.buffer.read(); raise SystemExit(3)"


def target(script: str) -> CommandTarget:
    return CommandTarget((sys.executable, "-c", script))


def test_archive_retention_keeps_newest_valid_archives_and_replays_real_target(tmp_path) -> None:
    harness = DifferentialHarness(candidate=target(BUGGY_SCRIPT), oracle=target(ECHO_SCRIPT))
    archive_root = tmp_path / "archives"
    archive_root.mkdir()

    archives = []
    for index in range(3):
        repro = harness.write_repro(
            tmp_path / f"repro-{index}",
            input_bytes=f"BUG-{index}".encode(),
            metadata={"index": index},
        )
        archive = export_repro_archive(repro.path, archive_root / f"case-{index}.zip")
        timestamp = 1_700_000_000 + index
        os.utime(archive, times=(timestamp, timestamp))
        archives.append(archive)

    malformed = archive_root / "malformed.zip"
    with zipfile.ZipFile(malformed, "w", compression=zipfile.ZIP_STORED) as handle:
        handle.writestr("unexpected", b"nope")
    unrelated = archive_root / "notes.txt"
    unrelated.write_text("keep me", encoding="utf-8")
    directory = archive_root / "directory"
    directory.mkdir()

    result = enforce_repro_archive_retention(archive_root, max_archives=2)

    assert result.kept == (archives[2], archives[1])
    assert result.removed == (archives[0],)
    assert set(result.ignored) == {malformed, unrelated, directory}
    assert tuple(evidence.path for evidence in result.kept_evidence) == result.kept
    assert not archives[0].exists()
    assert malformed.exists()
    assert unrelated.exists()
    assert directory.is_dir()

    for evidence in result.kept_evidence:
        replay = replay_repro_archive(
            harness,
            evidence.path,
            expected_archive_sha256=evidence.archive_sha256,
            require_reproduction=True,
        )
        assert replay.reproduced


def test_archive_retention_total_byte_budget_is_greedy_and_replayable(tmp_path) -> None:
    harness = DifferentialHarness(candidate=target(BUGGY_SCRIPT), oracle=target(ECHO_SCRIPT))
    root = tmp_path / "archives"
    root.mkdir()
    inputs = (b"BUG-old", b"BUG-" + b"x" * 4096, b"BUG-new")
    archives = []

    for index, input_bytes in enumerate(inputs):
        repro = harness.write_repro(
            tmp_path / f"budget-repro-{index}", input_bytes=input_bytes
        )
        archive = export_repro_archive(repro.path, root / f"budget-{index}.zip")
        timestamp = 1_700_100_000 + index
        os.utime(archive, times=(timestamp, timestamp))
        archives.append(archive)

    byte_budget = archives[2].stat().st_size + archives[0].stat().st_size
    assert archives[1].stat().st_size > archives[0].stat().st_size

    result = enforce_repro_archive_retention(
        root,
        max_archives=3,
        max_total_archive_bytes=byte_budget,
    )

    assert result.kept == (archives[2], archives[0])
    assert result.removed == (archives[1],)
    assert sum(evidence.size_bytes for evidence in result.kept_evidence) <= byte_budget
    for evidence in result.kept_evidence:
        replay = replay_repro_archive(
            harness,
            evidence.path,
            expected_archive_sha256=evidence.archive_sha256,
            require_reproduction=True,
        )
        assert replay.reproduced


def test_archive_retention_preserves_distinct_failure_signatures_before_duplicates(
    tmp_path,
) -> None:
    mismatch_harness = DifferentialHarness(
        candidate=target(BUGGY_SCRIPT), oracle=target(ECHO_SCRIPT)
    )
    exit_harness = DifferentialHarness(
        candidate=target(EXIT_SCRIPT), oracle=target(ECHO_SCRIPT)
    )
    root = tmp_path / "archives"
    root.mkdir()

    unique_old = export_repro_archive(
        exit_harness.write_repro(tmp_path / "exit-repro", input_bytes=b"BUG-old").path,
        root / "unique-old.zip",
    )
    duplicate_middle = export_repro_archive(
        mismatch_harness.write_repro(
            tmp_path / "mismatch-middle", input_bytes=b"BUG-middle"
        ).path,
        root / "duplicate-middle.zip",
    )
    duplicate_new = export_repro_archive(
        mismatch_harness.write_repro(
            tmp_path / "mismatch-new", input_bytes=b"BUG-new"
        ).path,
        root / "duplicate-new.zip",
    )
    for index, archive in enumerate((unique_old, duplicate_middle, duplicate_new)):
        timestamp = 1_700_200_000 + index
        os.utime(archive, times=(timestamp, timestamp))

    result = enforce_repro_archive_retention(
        root,
        max_archives=2,
        preserve_unique_failures=True,
    )

    assert result.kept == (duplicate_new, unique_old)
    assert result.removed == (duplicate_middle,)
    by_path = {evidence.path: evidence for evidence in result.kept_evidence}
    assert replay_repro_archive(
        mismatch_harness,
        duplicate_new,
        expected_archive_sha256=by_path[duplicate_new].archive_sha256,
        require_reproduction=True,
    ).reproduced
    assert replay_repro_archive(
        exit_harness,
        unique_old,
        expected_archive_sha256=by_path[unique_old].archive_sha256,
        require_reproduction=True,
    ).reproduced


def test_archive_retention_evidence_rejects_post_retention_path_replacement_before_launch(
    tmp_path,
) -> None:
    harness = DifferentialHarness(candidate=target(BUGGY_SCRIPT), oracle=target(ECHO_SCRIPT))
    root = tmp_path / "archives"
    root.mkdir()
    archive = export_repro_archive(
        harness.write_repro(tmp_path / "original-repro", input_bytes=b"BUG-original").path,
        root / "retained.zip",
    )
    replacement = export_repro_archive(
        harness.write_repro(
            tmp_path / "replacement-repro", input_bytes=b"BUG-replacement"
        ).path,
        tmp_path / "replacement.zip",
    )

    result = enforce_repro_archive_retention(root, max_archives=1)
    evidence = result.kept_evidence[0]

    assert evidence.path == archive
    assert evidence.size_bytes == len(archive.read_bytes())
    assert evidence.archive_sha256 == hashlib.sha256(archive.read_bytes()).hexdigest()

    archive.write_bytes(replacement.read_bytes())
    marker = tmp_path / "candidate-executed"
    marker_script = (
        "from pathlib import Path; import sys; "
        f"Path({str(marker)!r}).write_text('ran', encoding='utf-8'); "
        "sys.stdout.buffer.write(sys.stdin.buffer.read())"
    )
    marker_harness = DifferentialHarness(
        candidate=target(marker_script),
        oracle=target(ECHO_SCRIPT),
    )

    with pytest.raises(ValueError, match="sha256 does not match expected digest"):
        replay_repro_archive(
            marker_harness,
            archive,
            expected_archive_sha256=evidence.archive_sha256,
            require_same_context=False,
        )

    assert not marker.exists()


def test_archive_retention_tie_breaks_by_filename_and_ignores_symlinks(tmp_path) -> None:
    harness = DifferentialHarness(candidate=target(BUGGY_SCRIPT), oracle=target(ECHO_SCRIPT))
    root = tmp_path / "archives"
    root.mkdir()
    repro = harness.write_repro(tmp_path / "repro", input_bytes=b"BUG")
    first = export_repro_archive(repro.path, root / "a.zip")
    second = export_repro_archive(repro.path, root / "b.zip")
    os.utime(first, ns=(10, 10))
    os.utime(second, ns=(10, 10))

    symlink = root / "link.zip"
    try:
        symlink.symlink_to(second)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unavailable")

    result = enforce_repro_archive_retention(root, max_archives=1)

    assert result.kept == (first,)
    assert result.removed == (second,)
    assert result.ignored == (symlink,)
    assert result.kept_evidence[0].path == first
    assert symlink.is_symlink()


def test_archive_retention_validates_limit_type_before_scanning(tmp_path) -> None:
    with pytest.raises(TypeError, match="max_archives must be an int"):
        enforce_repro_archive_retention(tmp_path, max_archives=True)
    with pytest.raises(ValueError, match="max_archives must be non-negative"):
        enforce_repro_archive_retention(tmp_path, max_archives=-1)
    with pytest.raises(TypeError, match="max_total_archive_bytes must be an int or None"):
        enforce_repro_archive_retention(
            tmp_path, max_archives=1, max_total_archive_bytes=True
        )
    with pytest.raises(ValueError, match="max_total_archive_bytes must be non-negative"):
        enforce_repro_archive_retention(
            tmp_path, max_archives=1, max_total_archive_bytes=-1
        )
    with pytest.raises(TypeError, match="preserve_unique_failures must be a bool"):
        enforce_repro_archive_retention(
            tmp_path, max_archives=1, preserve_unique_failures=1
        )
