from jobs import job_runner
from jobs.job_history import list_job_runs
from alerts.alert_manager import list_alerts


def test_run_registered_job_records_success_history(monkeypatch, tmp_path):
    db_path = str(tmp_path / "jobs.db")

    monkeypatch.setattr(
        job_runner,
        "_run_handler",
        lambda job, db_path, dry_run, config: {"ok": True, "summary": {"selected_count": 1}, "warnings": []},
    )

    result = job_runner.run_registered_job("weekly_paper_cycle", db_path=db_path, dry_run=True)
    history = list_job_runs(db_path=db_path)

    assert result["ok"] is True
    assert result["status"] == "success"
    assert result["dry_run"] is True
    assert history["count"] == 1
    assert history["job_runs"][0]["job_name"] == "weekly_paper_cycle"


def test_run_registered_job_failure_records_history_and_alert(monkeypatch, tmp_path):
    db_path = str(tmp_path / "jobs.db")

    monkeypatch.setattr(
        job_runner,
        "_run_handler",
        lambda job, db_path, dry_run, config: {"ok": False, "error": "boom", "errors": ["boom"]},
    )

    result = job_runner.run_registered_job("weekly_paper_cycle", db_path=db_path, dry_run=True)
    history = list_job_runs(db_path=db_path)
    alerts = list_alerts(db_path=db_path)

    assert result["ok"] is False
    assert result["status"] == "failed"
    assert history["job_runs"][0]["status"] == "failed"
    assert alerts["count"] >= 1
    assert {alert["alert_type"] for alert in alerts["alerts"]} & {"job_failed", "paper_cycle_failed"}


def test_run_registered_job_unknown_returns_clean_error(tmp_path):
    result = job_runner.run_registered_job("missing_job", db_path=str(tmp_path / "jobs.db"))

    assert result["ok"] is False
    assert result["status"] == "failed"
    assert "Job not found" in result["errors"][0]


def test_run_due_jobs_runs_due_jobs_and_collects_errors(monkeypatch, tmp_path):
    monkeypatch.setattr(
        job_runner,
        "list_registered_jobs",
        lambda: {
            "ok": True,
            "jobs": [
                {"job_name": "job_a", "enabled": True, "schedule": {"daily_at": "08:00"}},
                {"job_name": "job_b", "enabled": True, "schedule": {"daily_at": "08:00"}},
            ],
        },
    )
    monkeypatch.setattr(
        job_runner,
        "run_registered_job",
        lambda job_name, db_path=None, dry_run=True, config=None: {
            "ok": job_name == "job_a",
            "status": "success" if job_name == "job_a" else "failed",
            "warnings": [],
            "errors": [] if job_name == "job_a" else ["boom"],
        },
    )

    result = job_runner.run_due_jobs(db_path=str(tmp_path / "jobs.db"), dry_run=True)

    assert result["ran_count"] == 2
    assert result["ok"] is False
    assert result["errors"] == ["boom"]


def test_paper_cycle_handler_dry_run_does_not_execute_paper_cycle():
    result = job_runner._run_handler(
        {"handler_name": "paper_cycle", "config": {}},
        db_path="unused.db",
        dry_run=True,
        config=None,
    )

    assert result["ok"] is True
    assert result["dry_run"] is True
    assert "paper cycle was not executed" in result["message"]


def test_performance_report_handler_runs_offline_report(monkeypatch, tmp_path):
    captured = {}

    monkeypatch.setattr(
        job_runner,
        "generate_performance_diagnostics_report",
        lambda **kwargs: captured.update(kwargs) or {"ok": True, "report_type": "performance_diagnostics", "warnings": []},
    )

    result = job_runner._run_handler(
        {"handler_name": "performance_report", "config": {}},
        db_path=str(tmp_path / "jobs.db"),
        dry_run=True,
        config=None,
    )

    assert result["ok"] is True
    assert result["report_type"] == "performance_diagnostics"
    assert captured["format"] == "dict"


def test_stress_test_handler_runs_offline_suite(monkeypatch, tmp_path):
    captured = {}

    monkeypatch.setattr(
        job_runner,
        "run_default_stress_suite",
        lambda **kwargs: captured.update(kwargs) or {"ok": True, "mode": "stress_test", "scenario_count": 1, "warnings": []},
    )

    result = job_runner._run_handler(
        {"handler_name": "stress_test", "config": {}},
        db_path=str(tmp_path / "jobs.db"),
        dry_run=True,
        config=None,
    )

    assert result["ok"] is True
    assert result["mode"] == "stress_test"
    assert captured["config"]["db_path"] == str(tmp_path / "jobs.db")
