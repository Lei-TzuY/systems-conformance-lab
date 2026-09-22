from __future__ import annotations

import json

from systems_conformance import (
    ComparisonResult,
    DifferentialHarness,
    DifferentialRun,
    ExecutionResult,
    SQLiteTwoConnectionFeedbackEvaluator,
    SQLiteTwoConnectionScenarioMutations,
    SQLiteTwoConnectionScenarioTarget,
    StreamCapture,
    run_feedback_guided_campaign,
    sqlite_two_connection_feedback_features,
)


def _capture(text: str = "", *, truncated: bool = False) -> StreamCapture:
    return StreamCapture(text=text, total_bytes=len(text.encode()), truncated=truncated)


def _execution(*, exit_code: int = 0, stdout: str = "", stderr: str = "") -> ExecutionResult:
    return ExecutionResult(
        argv=("sqlite-two-connection",),
        duration_ms=1,
        timed_out=False,
        exit_code=exit_code,
        signal=None,
        stdout=_capture(stdout),
        stderr=_capture(stderr),
    )


def _case(*, mode: str = "immediate") -> bytes:
    return json.dumps(
        {
            "setup": [
                "CREATE TABLE items(v INTEGER NOT NULL)",
                "INSERT INTO items VALUES (0)",
            ],
            "steps": [
                {"connection": "a", "op": "begin", "mode": mode},
                {"connection": "a", "op": "execute", "sql": "UPDATE items SET v = 1"},
                {
                    "connection": "b",
                    "op": "try_query",
                    "sql": "SELECT v FROM items",
                },
                {"connection": "a", "op": "rollback"},
            ],
        },
        separators=(",", ":"),
    ).encode()


def _mutate(case: bytes, mutation_index: int) -> bytes:
    corpus = SQLiteTwoConnectionScenarioMutations([case])
    generated = corpus.case_count - 1
    if generated <= 0:
        return case
    return corpus(1 + (mutation_index % generated))


def test_feedback_features_capture_bounded_transcript_structure_without_raw_values() -> None:
    stdout = json.dumps(
        {
            "steps": [
                {"connection": "a", "op": "begin", "mode": "exclusive"},
                {
                    "connection": "b",
                    "op": "try_query",
                    "ok": True,
                    "columns": ["secret-column"],
                    "rows": [[123456, "secret-value"]],
                },
                {
                    "connection": "a",
                    "op": "try_execute",
                    "ok": False,
                    "error": "SQLITE_BUSY_SNAPSHOT",
                    "error_code": 517,
                },
            ]
        },
        separators=(",", ":"),
    )
    execution = _execution(stdout=stdout)
    run = DifferentialRun(
        candidate=execution,
        oracle=execution,
        comparison=ComparisonResult(equivalent=True, classification="match", mismatches=()),
        signature=None,
    )

    features = sqlite_two_connection_feedback_features(run)

    assert "comparison:match" in features
    assert "candidate:transcript:steps:3" in features
    assert "candidate:step:connection:a" in features
    assert "candidate:step:connection:b" in features
    assert "candidate:step:op:begin" in features
    assert "candidate:step:op:try_query" in features
    assert "candidate:step:op:try_execute" in features
    assert "candidate:try:ok:1" in features
    assert "candidate:try:ok:0" in features
    assert "candidate:try:error:SQLITE_BUSY_SNAPSHOT" in features
    assert "candidate:result:columns:1" in features
    assert "candidate:result:rows:1" in features
    assert "candidate:result:value-kind:int" in features
    assert "candidate:result:value-kind:text" in features
    assert all(
        "secret-column" not in feature
        and "secret-value" not in feature
        and "123456" not in feature
        and "517" not in feature
        for feature in features
    )


def test_feedback_features_bucket_worker_errors_without_embedding_stderr() -> None:
    candidate = _execution(
        exit_code=4,
        stderr="result_error: transcript exceeds max_transcript_bytes: 123456\n",
    )
    oracle = _execution(stdout='{"steps":[]}\n')
    run = DifferentialRun(
        candidate=candidate,
        oracle=oracle,
        comparison=ComparisonResult(
            equivalent=False,
            classification="product_mismatch",
            mismatches=("exit_code", "stdout", "stderr"),
        ),
        signature=None,
    )

    features = sqlite_two_connection_feedback_features(run)

    assert "comparison:product_mismatch" in features
    assert "candidate:stderr-kind:result_error" in features
    assert "oracle:transcript:steps:0" in features
    assert all("123456" not in feature for feature in features)


def test_real_feedback_campaign_discovers_exclusive_reader_contention() -> None:
    harness = DifferentialHarness(
        candidate=SQLiteTwoConnectionScenarioTarget(journal_mode="delete").as_command_target(),
        oracle=SQLiteTwoConnectionScenarioTarget(journal_mode="wal").as_command_target(),
        timeout_seconds=5.0,
    )

    campaign = run_feedback_guided_campaign(
        seeds=(_case(mode="immediate"),),
        mutate=_mutate,
        evaluate=SQLiteTwoConnectionFeedbackEvaluator(harness),
        mutations_per_case=2,
        max_evaluations=4,
        max_corpus_entries=8,
        max_unique_failures=4,
    )

    assert campaign.evaluations >= 3
    assert "comparison:match" in campaign.features
    assert "comparison:product_mismatch" in campaign.features
    assert "candidate:step:op:try_query" in campaign.features
    assert "candidate:try:ok:0" in campaign.features
    assert "candidate:try:error:SQLITE_BUSY" in campaign.features
    assert "oracle:try:ok:1" in campaign.features
    assert campaign.failures
    assert campaign.failures[0].comparison.classification == "product_mismatch"
    assert json.loads(campaign.failures[0].case)["steps"][0]["mode"] == "exclusive"
    assert campaign.failures[0].comparison.candidate_infrastructure_error is None
    assert campaign.failures[0].comparison.oracle_infrastructure_error is None
