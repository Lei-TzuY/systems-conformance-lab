import json

from systems_conformance import (
    ComparisonResult,
    DifferentialHarness,
    DifferentialRun,
    ExecutionResult,
    SQLiteTransactionFeedbackEvaluator,
    SQLiteTransactionParameterMutations,
    SQLiteTransactionTarget,
    StreamCapture,
    run_feedback_guided_campaign,
    sqlite_transaction_feedback_features,
)


def _capture(text: str = "", *, truncated: bool = False) -> StreamCapture:
    return StreamCapture(text=text, total_bytes=len(text.encode()), truncated=truncated)


def _execution(
    *,
    exit_code: int = 0,
    stdout: str = "",
    stderr: str = "",
) -> ExecutionResult:
    return ExecutionResult(
        argv=("sqlite-transaction",),
        duration_ms=1,
        timed_out=False,
        exit_code=exit_code,
        signal=None,
        stdout=_capture(stdout),
        stderr=_capture(stderr),
    )


def test_feedback_features_capture_transcript_structure_without_raw_values() -> None:
    stdout = json.dumps(
        {
            "transaction": [
                {"columns": ["a", "b"], "rows": [[1, "secret-value"]]},
                {"columns": [], "rows": []},
            ],
            "observation": {
                "columns": ["v"],
                "rows": [[None], [{"$blob": "00ff"}]],
            },
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

    features = sqlite_transaction_feedback_features(run)

    assert "comparison:match" in features
    assert "candidate:transaction:statements:2" in features
    assert "candidate:transaction:result:columns:2" in features
    assert "candidate:transaction:result:rows:1" in features
    assert "candidate:transaction:result:value-kind:int" in features
    assert "candidate:transaction:result:value-kind:text" in features
    assert "candidate:observation:result:rows:2" in features
    assert "candidate:observation:result:value-kind:null" in features
    assert "candidate:observation:result:value-kind:blob" in features
    assert all("secret-value" not in feature and "00ff" not in feature for feature in features)


def test_feedback_features_bucket_errors_without_embedding_stderr() -> None:
    candidate = _execution(exit_code=4, stderr="result_error: result exceeds 123456\n")
    oracle = _execution(
        stdout='{"transaction":[],"observation":{"columns":[],"rows":[]}}\n'
    )
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

    features = sqlite_transaction_feedback_features(run)

    assert "comparison:product_mismatch" in features
    assert "candidate:stderr-kind:result_error" in features
    assert "oracle:transaction:statements:0" in features
    assert "oracle:observation:result:rows:0" in features
    assert all("123456" not in feature for feature in features)


def _row_budget_case(threshold: int = 1) -> bytes:
    return json.dumps(
        {
            "setup": [
                "CREATE TABLE items(v INTEGER)",
                "INSERT INTO items VALUES(-1)",
                "INSERT INTO items VALUES(0)",
                "INSERT INTO items VALUES(1)",
            ],
            "transaction": [
                {
                    "sql": "SELECT v FROM items WHERE v >= ? ORDER BY v",
                    "params": [threshold],
                }
            ],
            "observe": {"sql": "SELECT count(*) FROM items", "params": []},
        },
        separators=(",", ":"),
    ).encode()


def _mutate_transaction_case(case: bytes, mutation_index: int) -> bytes:
    corpus = SQLiteTransactionParameterMutations([case])
    generated = corpus.case_count - 1
    if generated <= 0:
        return case
    return corpus(1 + (mutation_index % generated))


def test_real_sqlite_feedback_campaign_admits_transcript_coverage_and_failure() -> None:
    harness = DifferentialHarness(
        candidate=SQLiteTransactionTarget(max_result_rows=1).as_command_target(),
        oracle=SQLiteTransactionTarget(max_result_rows=10).as_command_target(),
    )
    evaluate = SQLiteTransactionFeedbackEvaluator(harness)

    campaign = run_feedback_guided_campaign(
        seeds=(_row_budget_case(),),
        mutate=_mutate_transaction_case,
        evaluate=evaluate,
        mutations_per_case=2,
        max_evaluations=6,
        max_corpus_entries=8,
        max_unique_failures=4,
    )

    assert campaign.evaluations >= 2
    assert "candidate:transaction:result:rows:1" in campaign.features
    assert "candidate:stderr-kind:result_error" in campaign.features
    assert "comparison:product_mismatch" in campaign.features
    assert campaign.failures
    assert campaign.failures[0].comparison.classification == "product_mismatch"
    assert campaign.failures[0].comparison.candidate_infrastructure_error is None
    assert campaign.failures[0].comparison.oracle_infrastructure_error is None
