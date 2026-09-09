import sys
from pathlib import Path

from systems_conformance import CommandTarget, DifferentialHarness


def test_implicit_context_snapshot_changes_replay_identity(monkeypatch, tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()

    monkeypatch.chdir(first)
    monkeypatch.setenv("CONFORMANCE_IMPLICIT_CONTEXT", "before")
    first_target = CommandTarget((sys.executable, "-c", "pass"))
    first_harness = DifferentialHarness(candidate=first_target, oracle=first_target)

    monkeypatch.chdir(second)
    monkeypatch.setenv("CONFORMANCE_IMPLICIT_CONTEXT", "after")
    second_target = CommandTarget((sys.executable, "-c", "pass"))
    second_harness = DifferentialHarness(candidate=second_target, oracle=second_target)

    assert first_target.cwd is None
    assert first_target.env is None
    assert second_target.cwd is None
    assert second_target.env is None
    assert first_harness.replay_context_sha256 != second_harness.replay_context_sha256


def test_implicit_context_snapshot_drives_real_child_process(monkeypatch, tmp_path: Path) -> None:
    construction_dir = tmp_path / "construction"
    later_dir = tmp_path / "later"
    construction_dir.mkdir()
    later_dir.mkdir()
    (construction_dir / "marker.txt").write_text("anchored", encoding="utf-8")
    (later_dir / "marker.txt").write_text("drifted", encoding="utf-8")

    monkeypatch.chdir(construction_dir)
    monkeypatch.setenv("CONFORMANCE_IMPLICIT_CONTEXT", "before")
    script = (
        "import os; from pathlib import Path; "
        "print(Path('marker.txt').read_text(encoding='utf-8')); "
        "print(os.environ['CONFORMANCE_IMPLICIT_CONTEXT'])"
    )
    target = CommandTarget((sys.executable, "-c", script))
    harness = DifferentialHarness(candidate=target, oracle=target)
    initial_context = harness.replay_context_sha256

    monkeypatch.chdir(later_dir)
    monkeypatch.setenv("CONFORMANCE_IMPLICIT_CONTEXT", "after")

    result = harness.evaluate(b"")

    assert harness.replay_context_sha256 == initial_context
    assert result.comparison.classification == "match"
    assert result.candidate.exit_code == 0
    assert result.candidate.stdout.text.splitlines() == ["anchored", "before"]
    assert result.oracle.stdout.text.splitlines() == ["anchored", "before"]