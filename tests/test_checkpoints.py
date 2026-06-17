from db.checkpoints import (
    complete_pipeline_run,
    fail_pipeline_run,
    get_latest_checkpoint,
    get_pipeline_run,
    list_checkpoints,
    list_recent_pipeline_runs,
    record_checkpoint,
    start_pipeline_run,
)


def test_pipeline_run_start_complete_and_list(tmp_path):
    db_path = str(tmp_path / "pipeline.db")

    started = start_pipeline_run(db_path, "paper_cycle", metadata={"universe": "mega_cap"})
    run_id = started["run_id"]
    completed = complete_pipeline_run(
        db_path,
        run_id,
        {
            "selected_count": 2,
            "logged_count": 1,
            "scan_execution_summary": {
                "total_tickers": 10,
                "completed_tickers": 8,
                "failed_tickers": ["BAD"],
                "timed_out_tickers": ["SLOW"],
                "partial_results_used": True,
                "duration_seconds": 12.5,
            },
        },
    )
    fetched = get_pipeline_run(db_path, run_id)
    recent = list_recent_pipeline_runs(db_path, limit=5)

    assert started["ok"] is True
    assert completed["ok"] is True
    assert fetched["pipeline_run"]["status"] == "completed"
    assert fetched["pipeline_run"]["total_tickers"] == 10
    assert fetched["pipeline_run"]["failed_tickers"] == 1
    assert fetched["pipeline_run"]["timed_out_tickers"] == 1
    assert fetched["pipeline_run"]["partial_results_used"] == 1
    assert recent["count"] == 1


def test_pipeline_run_fail_records_error(tmp_path):
    db_path = str(tmp_path / "pipeline_fail.db")

    started = start_pipeline_run(db_path, "paper_cycle")
    failed = fail_pipeline_run(db_path, started["run_id"], {"error": "boom"})

    assert failed["ok"] is True
    assert failed["pipeline_run"]["status"] == "failed"
    assert failed["pipeline_run"]["error_json"]["error"] == "boom"


def test_checkpoints_record_list_and_latest(tmp_path):
    db_path = str(tmp_path / "checkpoints.db")
    run_id = start_pipeline_run(db_path, "paper_cycle")["run_id"]

    first = record_checkpoint(db_path, run_id, "universe_loaded", "completed", payload={"count": 3})
    second = record_checkpoint(db_path, run_id, "async_scan_completed", "completed", payload={"completed_tickers": 3})
    checkpoints = list_checkpoints(db_path, run_id)
    latest = get_latest_checkpoint(db_path, run_id)

    assert first["ok"] is True
    assert second["ok"] is True
    assert checkpoints["count"] == 2
    assert checkpoints["checkpoints"][0]["payload_json"]["count"] == 3
    assert latest["checkpoint"]["checkpoint_name"] == "async_scan_completed"

