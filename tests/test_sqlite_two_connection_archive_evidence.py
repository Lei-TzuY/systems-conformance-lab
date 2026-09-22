from __future__ import annotations

import json
import shutil

import pytest

from systems_conformance import (
    DifferentialHarness,
    SQLiteTwoConnectionScenarioTarget,
    discover_sqlite_two_connection_failure_to_archive,
    replay_repro_archive,
)


def _case(*, mode: str = "immediate") -> bytes:
    return json.dumps(
        {
            "setup": [
                "CREATE TABLE items(v INTEGER NOT NULL)",
                "INSERT INTO items VALUES (0)",
                "CREATE TABLE noise(v INTEGER)",
            ],
            "steps": [
                {"connection": "a", "op": "query", "sql": "SELECT 111 AS noise"},
                {"connection": "a", "op": "begin", "mode": mode},
                {
                    "connection": "b",
                    "op": "try_query",
                    "sql": "SELECT v FROM items WHERE v >= ?",
                    "params": [-987654],
                },
                {"connection": "a", "op": "rollback"},
                {
                    "connection": "b",
                    "op": "query",
                    "sql": "SELECT ? AS tail",
                    "params": [999],
                },
            ],
        },
        separators=(",", ":"),
    ).encode()


def _harness(*, same_journal: bool = False) -> DifferentialHarness:
    return DifferentialHarness(
        candidate=SQLiteTwoConnectionScenarioTarget(journal_mode="delete").as_command_target(),
        oracle=SQLiteTwoConnectionScenarioTarget(
            journal_mode="delete" if same_journal else "wal"
        ).as_command_target(),
        timeout_seconds=5.0,
    )


def test_discovery_exports_portable_archive_and_replays_with_transport_digest(
    tmp_path,
) -> None:
    harness = _harness()
    result = discover_sqlite_two_connection_failure_to_archive(
        (_case(),),
        harness=harness,
        repro_destination=tmp_path / "repro",
        archive_path=tmp_path / "portable.zip",
        mutations_per_case=2,
        max_evaluations=4,
        max_corpus_entries=8,
        max_evaluations_per_phase=64,
        metadata={"source": "sqlite-two-connection-archive-evidence"},
    )

    assert result.archive_path == tmp_path / "portable.zip"
    assert result.archive_path.is_file()
    assert len(result.archive_sha256) == 64
    assert set(result.archive_sha256) <= set("0123456789abcdef")
    assert result.replay.archive_sha256 == result.archive_sha256
    assert result.replay.input_bytes == result.reduced
    assert result.replay.signature == result.failure.signature
    assert result.replay.reproduced is True
    assert result.replay.metadata["source"] == "sqlite-two-connection-archive-evidence"

    transported = tmp_path / "transported.zip"
    shutil.copyfile(result.archive_path, transported)
    replay = replay_repro_archive(
        harness,
        transported,
        expected_archive_sha256=result.archive_sha256,
        require_reproduction=True,
    )

    assert replay.archive_sha256 == result.archive_sha256
    assert replay.input_bytes == result.reduced
    assert replay.signature == result.failure.signature
    assert replay.reproduced is True


def test_no_failure_publishes_neither_repro_nor_archive(tmp_path) -> None:
    repro = tmp_path / "repro"
    archive = tmp_path / "portable.zip"

    with pytest.raises(ValueError, match="discovered no stable failure"):
        discover_sqlite_two_connection_failure_to_archive(
            (_case(),),
            harness=_harness(same_journal=True),
            repro_destination=repro,
            archive_path=archive,
            mutations_per_case=2,
            max_evaluations=3,
            max_corpus_entries=8,
            max_evaluations_per_phase=16,
        )

    assert not repro.exists()
    assert not archive.exists()


def test_existing_archive_destination_is_rejected_before_discovery(tmp_path) -> None:
    repro = tmp_path / "repro"
    archive = tmp_path / "portable.zip"
    archive.write_bytes(b"already-owned")

    with pytest.raises(FileExistsError, match="destination already exists"):
        discover_sqlite_two_connection_failure_to_archive(
            (_case(),),
            harness=_harness(),
            repro_destination=repro,
            archive_path=archive,
            mutations_per_case=2,
            max_evaluations=4,
            max_corpus_entries=8,
            max_evaluations_per_phase=64,
        )

    assert not repro.exists()
    assert archive.read_bytes() == b"already-owned"
