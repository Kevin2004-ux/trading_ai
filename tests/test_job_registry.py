from jobs.job_registry import get_registered_job, list_registered_jobs, register_job


def test_default_jobs_include_safe_scheduled_workflows():
    result = list_registered_jobs()
    names = {job["job_name"] for job in result["jobs"]}
    types = {job["job_type"] for job in result["jobs"]}

    assert result["ok"] is True
    assert "weekly_paper_cycle" in names
    assert "readiness_check" in names
    assert "performance_report" in names
    assert "stress_test" in names
    assert "paper_cycle" in types
    assert "performance_report" in types
    assert "live_dry_run" in types
    assert "stress_test" in types
    stress_job = next(job for job in result["jobs"] if job["job_name"] == "stress_test")
    assert stress_job["enabled"] is False


def test_register_job_adds_custom_safe_job():
    result = register_job(
        job_name="test_readiness_job",
        job_type="readiness_check",
        handler_name="readiness_check",
        schedule={"daily_at": "08:00"},
    )
    lookup = get_registered_job("test_readiness_job")

    assert result["ok"] is True
    assert lookup["ok"] is True
    assert lookup["jobs"][0]["handler_name"] == "readiness_check"


def test_register_job_rejects_unsupported_type():
    result = register_job(
        job_name="bad_job",
        job_type="order_execution",
        handler_name="place_order",
    )

    assert result["ok"] is False
    assert any("Unsupported job_type" in error for error in result["errors"])


def test_get_registered_job_missing_returns_clean_error():
    result = get_registered_job("does_not_exist")

    assert result["ok"] is False
    assert result["jobs"] == []
