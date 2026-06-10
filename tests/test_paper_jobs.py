from jobs.paper_jobs import (
    run_daily_paper_review_job,
    run_paper_summary_job,
    run_weekly_paper_cycle_job,
)


def test_weekly_paper_cycle_job_calls_paper_trader(monkeypatch):
    captured = {}

    def fake_run_paper_trade_cycle(**kwargs):
        captured.update(kwargs)
        return {
            "ok": True,
            "mode": "paper_trading",
            "summary": {"logged_count": 1, "message": "simulated"},
            "warning": "simulated only",
            "errors": [],
        }

    monkeypatch.setattr("jobs.paper_jobs.run_paper_trade_cycle", fake_run_paper_trade_cycle)

    result = run_weekly_paper_cycle_job(universe="large_cap", max_tickers=123)

    assert result["ok"] is True
    assert result["job"] == "weekly_paper_cycle"
    assert result["mode"] == "paper_trading"
    assert result["paper_cycle"]["summary"]["logged_count"] == 1
    assert captured["universe"] == "large_cap"
    assert captured["max_tickers"] == 123


def test_daily_paper_review_job_calls_paper_reviewer(monkeypatch):
    captured = {}

    def fake_review_paper_portfolio(**kwargs):
        captured.update(kwargs)
        return {
            "ok": True,
            "mode": "paper_trading",
            "warning": "simulated only",
            "errors": [],
        }

    monkeypatch.setattr("jobs.paper_jobs.review_paper_portfolio", fake_review_paper_portfolio)

    result = run_daily_paper_review_job(
        update_outcomes=False,
        include_trade_reviews=False,
        store_review_memory=True,
        db_path="paper.db",
    )

    assert result["ok"] is True
    assert result["job"] == "daily_paper_review"
    assert result["paper_review"]["mode"] == "paper_trading"
    assert captured["update_outcomes"] is False
    assert captured["include_trade_reviews"] is False
    assert captured["store_review_memory"] is True
    assert captured["db_path"] == "paper.db"


def test_paper_summary_job_calls_summary(monkeypatch):
    monkeypatch.setattr(
        "jobs.paper_jobs.get_paper_trading_summary",
        lambda db_path="strategy_library.db": {
            "ok": True,
            "mode": "paper_trading",
            "warning": "simulated only",
            "errors": [],
        },
    )

    result = run_paper_summary_job(db_path="paper.db")

    assert result["ok"] is True
    assert result["job"] == "paper_summary"
    assert result["paper_summary"]["mode"] == "paper_trading"
