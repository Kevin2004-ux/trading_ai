from jobs.job_history import get_job_run, list_job_runs, record_job_run


def test_record_list_and_get_job_run_round_trip(tmp_path):
    db_path = str(tmp_path / "jobs.db")

    recorded = record_job_run(
        db_path=db_path,
        job_run_id="job-run-1",
        job_name="weekly_paper_cycle",
        job_type="paper_cycle",
        status="success",
        started_at="2026-06-15T13:00:00+00:00",
        completed_at="2026-06-15T13:00:01+00:00",
        duration_seconds=1.0,
        dry_run=True,
        result={"ok": True, "summary": {"selected_count": 0}},
        warnings=["simulated only"],
        errors=[],
    )
    listed = list_job_runs(db_path=db_path)
    fetched = get_job_run(db_path=db_path, job_run_id="job-run-1")

    assert recorded["ok"] is True
    assert listed["ok"] is True
    assert listed["count"] == 1
    assert fetched["ok"] is True
    assert fetched["job_run"]["result_json"]["summary"]["selected_count"] == 0
    assert fetched["job_run"]["warning_json"] == ["simulated only"]


def test_get_job_run_missing_returns_clean_error(tmp_path):
    result = get_job_run(db_path=str(tmp_path / "jobs.db"), job_run_id="missing")

    assert result["ok"] is False
    assert result["job_run"] is None
