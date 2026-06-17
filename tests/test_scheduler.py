from jobs.scheduler import build_default_schedule, calculate_next_run, should_run_job


def test_calculate_next_run_interval_minutes():
    result = calculate_next_run(
        {"interval_minutes": 30, "timezone": "America/New_York"},
        now="2026-06-15T09:00:00-04:00",
    )

    assert result["ok"] is True
    assert result["next_run"].startswith("2026-06-15T09:30:00")


def test_calculate_next_run_daily_same_day_before_time():
    result = calculate_next_run(
        {"daily_at": "16:30", "timezone": "America/New_York"},
        now="2026-06-15T09:00:00-04:00",
    )

    assert result["ok"] is True
    assert result["next_run"].startswith("2026-06-15T16:30:00")


def test_calculate_next_run_weekly_after_time_rolls_forward():
    result = calculate_next_run(
        {"weekly_at": {"day": "MON", "time": "09:00"}, "timezone": "America/New_York"},
        now="2026-06-15T10:00:00-04:00",
    )

    assert result["ok"] is True
    assert result["next_run"].startswith("2026-06-22T09:00:00")


def test_market_days_only_skips_weekends():
    result = calculate_next_run(
        {"daily_at": "16:00", "timezone": "America/New_York", "market_days_only": True},
        now="2026-06-19T17:00:00-04:00",
    )

    assert result["ok"] is True
    assert result["next_run"].startswith("2026-06-22T16:00:00")


def test_market_days_only_string_false_is_respected():
    result = calculate_next_run(
        {"daily_at": "16:00", "timezone": "America/New_York", "market_days_only": "false"},
        now="2026-06-19T17:00:00-04:00",
    )

    assert result["ok"] is True
    assert result["next_run"].startswith("2026-06-20T16:00:00")


def test_should_run_job_handles_disabled_never_run_and_due():
    disabled = should_run_job({"enabled": False, "schedule": {"daily_at": "08:00"}})
    never_run = should_run_job({"enabled": True, "schedule": {"daily_at": "08:00"}})
    due = should_run_job(
        {
            "enabled": True,
            "schedule": {"daily_at": "08:00", "timezone": "America/New_York"},
            "last_run_at": "2026-06-14T08:00:00-04:00",
        },
        now="2026-06-15T09:00:00-04:00",
    )

    assert disabled["should_run"] is False
    assert never_run["should_run"] is True
    assert due["should_run"] is True


def test_build_default_schedule_is_disabled_by_default(monkeypatch):
    monkeypatch.delenv("SCHEDULER_ENABLED", raising=False)

    result = build_default_schedule()

    assert result["ok"] is True
    assert result["scheduler_enabled"] is False
    assert result["jobs"]
