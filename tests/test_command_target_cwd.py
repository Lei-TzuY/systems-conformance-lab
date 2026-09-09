from __future__ import annotations

import sys
from pathlib import Path

from systems_conformance import CommandTarget, DifferentialHarness


def test_relative_cwd_is_anchored_at_target_construction(tmp_path, monkeypatch) -> None:
    target_dir = tmp_path / "target"
    target_dir.mkdir()
    monkeypatch.chdir(tmp_path)

    command = CommandTarget((sys.executable, "-c", "pass"), cwd="target")

    assert command.cwd == str(target_dir)


def test_anchored_relative_cwd_survives_ambient_chdir(tmp_path, monkeypatch) -> None:
    target_dir = tmp_path / "target"
    other_dir = tmp_path / "other"
    target_dir.mkdir()
    other_dir.mkdir()
    marker = target_dir / "marker.txt"
    marker.write_text("anchored", encoding="utf-8")

    monkeypatch.chdir(tmp_path)
    command = CommandTarget(
        (
            sys.executable,
            "-c",
            "from pathlib import Path; print(Path('marker.txt').read_text(encoding='utf-8'))",
        ),
        cwd="target",
    )
    identity_before = command._replay_identity()

    monkeypatch.chdir(other_dir)
    harness = DifferentialHarness(candidate=command, oracle=command)
    result = harness.evaluate(b"")

    assert command._replay_identity() == identity_before
    assert Path(command.cwd) == target_dir
    assert result.comparison.classification == "match"
    assert result.candidate.exit_code == 0
    assert result.candidate.stdout.text.splitlines() == ["anchored"]
