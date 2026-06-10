from contextlib import redirect_stdout
from io import StringIO
import json

import cli


def _run_cli_and_capture(argv: list[str]) -> tuple[int, str]:
    stdout = StringIO()
    with redirect_stdout(stdout):
        exit_code = cli.main(argv)
    return exit_code, stdout.getvalue()


def test_cli_paper_cycle_prints_json_and_exits_zero(monkeypatch):
    captured = {}

    monkeypatch.setattr(
        "cli.run_weekly_paper_cycle_job",
        lambda **kwargs: captured.update(kwargs) or {
            "ok": True,
            "job": "weekly_paper_cycle",
            "mode": "paper_trading",
            "warning": "simulated only",
            "errors": [],
        },
    )

    exit_code, output = _run_cli_and_capture(
        [
            "paper-cycle",
            "--no-include-market-regime",
            "--no-include-relative-strength",
            "--include-options",
            "--prefer-options",
            "--max-option-contracts-per-trade",
            "2",
            "--no-include-portfolio-risk",
            "--no-include-position-sizing",
            "--no-include-memory-context",
            "--store-memory",
            "--account-size",
            "25000",
            "--risk-mode",
            "conservative",
        ]
    )
    output = output.strip()
    payload = json.loads(output)

    assert exit_code == 0
    assert payload["ok"] is True
    assert payload["job"] == "weekly_paper_cycle"
    assert captured["include_market_regime"] is False
    assert captured["include_relative_strength"] is False
    assert captured["include_options"] is True
    assert captured["prefer_options"] is True
    assert captured["max_option_contracts_per_trade"] == 2
    assert captured["include_portfolio_risk"] is False
    assert captured["include_position_sizing"] is False
    assert captured["include_memory_context"] is False
    assert captured["store_memory"] is True
    assert captured["account_size"] == 25000.0
    assert captured["risk_mode"] == "conservative"


def test_cli_paper_review_prints_json_and_exits_zero(monkeypatch):
    captured = {}

    monkeypatch.setattr(
        "cli.run_daily_paper_review_job",
        lambda **kwargs: captured.update(kwargs) or {
            "ok": True,
            "job": "daily_paper_review",
            "mode": "paper_trading",
            "warning": "simulated only",
            "errors": [],
        },
    )

    exit_code, output = _run_cli_and_capture(
        [
            "paper-review",
            "--no-include-trade-reviews",
            "--store-review-memory",
        ]
    )
    output = output.strip()
    payload = json.loads(output)

    assert exit_code == 0
    assert payload["ok"] is True
    assert payload["job"] == "daily_paper_review"
    assert captured["include_trade_reviews"] is False
    assert captured["store_review_memory"] is True


def test_cli_paper_summary_prints_json_and_exits_zero(monkeypatch):
    monkeypatch.setattr(
        "cli.run_paper_summary_job",
        lambda **kwargs: {
            "ok": True,
            "job": "paper_summary",
            "mode": "paper_trading",
            "warning": "simulated only",
            "errors": [],
        },
    )

    exit_code, output = _run_cli_and_capture(["paper-summary"])
    output = output.strip()
    payload = json.loads(output)

    assert exit_code == 0
    assert payload["ok"] is True
    assert payload["job"] == "paper_summary"


def test_cli_research_brief_prints_json_and_exits_zero(monkeypatch):
    captured = {}

    monkeypatch.setattr(
        "cli.get_deep_research_brief_tool",
        lambda **kwargs: captured.update(kwargs) or {
            "ok": True,
            "tool": "get_deep_research_brief_tool",
            "timestamp": "2026-06-07T00:00:00+00:00",
            "data": {
                "ticker": kwargs["ticker"],
                "brief_type": "deep_research",
            },
            "error": None,
        },
    )

    exit_code, output = _run_cli_and_capture(
        [
            "research-brief",
            "--ticker",
            "AAPL",
            "--no-include-sec-filings",
            "--no-include-earnings-transcripts",
            "--include-options",
            "--pretty",
        ]
    )
    payload = json.loads(output)

    assert exit_code == 0
    assert payload["ok"] is True
    assert payload["tool"] == "get_deep_research_brief_tool"
    assert captured["ticker"] == "AAPL"
    assert captured["include_sec_filings"] is False
    assert captured["include_earnings_transcripts"] is False
    assert captured["include_options"] is True


def test_cli_memory_search_prints_json_and_exits_zero(monkeypatch):
    captured = {}

    monkeypatch.setattr(
        "cli.search_trade_memory_tool",
        lambda **kwargs: captured.update(kwargs) or {
            "ok": True,
            "tool": "search_trade_memory_tool",
            "data": {"matches": []},
            "error": None,
        },
    )

    exit_code, output = _run_cli_and_capture(["memory-search", "--query", "AAPL breakout", "--top-k", "3"])
    payload = json.loads(output)

    assert exit_code == 0
    assert payload["tool"] == "search_trade_memory_tool"
    assert captured["query"] == "AAPL breakout"
    assert captured["top_k"] == 3


def test_cli_memory_store_note_prints_json_and_exits_zero(monkeypatch):
    captured = {}

    monkeypatch.setattr(
        "cli.store_trade_memory_tool",
        lambda **kwargs: captured.update(kwargs) or {
            "ok": True,
            "tool": "store_trade_memory_tool",
            "data": {"memory_id": "note-1"},
            "error": None,
        },
    )

    exit_code, output = _run_cli_and_capture(["memory-store-note", "--ticker", "AAPL", "--note", "Watch failed breakout retest."])
    payload = json.loads(output)

    assert exit_code == 0
    assert payload["tool"] == "store_trade_memory_tool"
    assert captured["item"]["ticker"] == "AAPL"
    assert captured["item"]["note"] == "Watch failed breakout retest."


def test_cli_review_closed_trades_prints_json_and_exits_zero(monkeypatch):
    captured = {}

    monkeypatch.setattr(
        "cli.review_closed_trades_tool",
        lambda **kwargs: captured.update(kwargs) or {
            "ok": True,
            "tool": "review_closed_trades_tool",
            "data": {"reviewed_count": 1, "errors": []},
            "error": None,
        },
    )

    exit_code, output = _run_cli_and_capture(["review-closed-trades", "--store-memory"])
    payload = json.loads(output)

    assert exit_code == 0
    assert payload["tool"] == "review_closed_trades_tool"
    assert captured["store_memory"] is True


def test_cli_trade_reviews_prints_json_and_exits_zero(monkeypatch):
    captured = {}

    monkeypatch.setattr(
        "cli.get_trade_reviews_tool",
        lambda **kwargs: captured.update(kwargs) or {
            "ok": True,
            "tool": "get_trade_reviews_tool",
            "data": {"count": 1, "reviews": [{"ticker": kwargs["ticker"]}]},
            "error": None,
        },
    )

    exit_code, output = _run_cli_and_capture(["trade-reviews", "--ticker", "AAPL", "--pretty"])
    payload = json.loads(output)

    assert exit_code == 0
    assert output.startswith("{\n  ")
    assert payload["tool"] == "get_trade_reviews_tool"
    assert captured["ticker"] == "AAPL"


def test_cli_report_prints_json_and_exits_zero(monkeypatch):
    captured = {}

    monkeypatch.setattr(
        "cli.generate_report_tool",
        lambda **kwargs: captured.update(kwargs) or {
            "ok": True,
            "tool": "generate_report_tool",
            "data": {
                "report_type": kwargs["report_type"],
                "format": kwargs["format"],
                "markdown": "# Report",
            },
            "error": None,
        },
    )

    exit_code, output = _run_cli_and_capture(["report", "--type", "performance", "--format", "dict"])
    payload = json.loads(output)

    assert exit_code == 0
    assert payload["tool"] == "generate_report_tool"
    assert captured["report_type"] == "performance"
    assert captured["format"] == "dict"


def test_cli_report_pretty_markdown_prints_markdown_only(monkeypatch):
    monkeypatch.setattr(
        "cli.generate_report_tool",
        lambda **kwargs: {
            "ok": True,
            "tool": "generate_report_tool",
            "data": {
                "report_type": kwargs["report_type"],
                "format": kwargs["format"],
                "markdown": "# Full Paper Trading Report\n\nSummary text.",
            },
            "error": None,
        },
    )

    exit_code, output = _run_cli_and_capture(["report", "--type", "full_paper_trading", "--format", "markdown", "--pretty"])

    assert exit_code == 0
    assert output.startswith("# Full Paper Trading Report")


def test_cli_env_check_prints_json(monkeypatch):
    monkeypatch.setattr(
        "cli.check_environment",
        lambda db_path="strategy_library.db": {
            "ok": True,
            "timestamp": "2026-06-08T00:00:00+00:00",
            "python_version": "3.11",
            "packages": {},
            "env_vars": {},
            "database": {"ok": True},
            "app": {"ok": True},
            "cli": {"ok": True},
            "warnings": [],
            "errors": [],
        },
    )

    exit_code, output = _run_cli_and_capture(["env-check", "--pretty"])
    payload = json.loads(output)

    assert exit_code == 0
    assert payload["ok"] is True
    assert payload["database"]["ok"] is True


def test_cli_live_dry_run_prints_json(monkeypatch):
    captured = {}

    monkeypatch.setattr(
        "cli.run_provider_dry_run",
        lambda **kwargs: captured.update(kwargs) or {
            "ok": True,
            "timestamp": "2026-06-08T00:00:00+00:00",
            "ticker": kwargs["ticker"],
            "checks": {},
            "warnings": ["dry run"],
            "errors": [],
        },
    )

    exit_code, output = _run_cli_and_capture(["live-dry-run", "--ticker", "AAPL", "--include-memory"])
    payload = json.loads(output)

    assert exit_code == 0
    assert payload["ticker"] == "AAPL"
    assert captured["include_memory"] is True


def test_cli_exits_one_when_job_fails(monkeypatch):
    monkeypatch.setattr(
        "cli.run_paper_summary_job",
        lambda **kwargs: {
            "ok": False,
            "job": "paper_summary",
            "mode": "paper_trading",
            "errors": ["boom"],
        },
    )

    exit_code, output = _run_cli_and_capture(["paper-summary"])
    output = output.strip()
    payload = json.loads(output)

    assert exit_code == 1
    assert payload["ok"] is False
    assert payload["errors"] == ["boom"]


def test_cli_pretty_output_is_valid_indented_json(monkeypatch):
    monkeypatch.setattr(
        "cli.run_paper_summary_job",
        lambda **kwargs: {
            "ok": True,
            "job": "paper_summary",
            "mode": "paper_trading",
            "warning": "simulated only",
            "errors": [],
        },
    )

    exit_code, output = _run_cli_and_capture(["paper-summary", "--pretty"])
    payload = json.loads(output)

    assert exit_code == 0
    assert output.startswith("{\n  ")
    assert payload["job"] == "paper_summary"


def test_cli_does_not_expose_buy_sell_or_order_commands():
    parser = cli.build_parser()
    subparsers_action = next(action for action in parser._actions if getattr(action, "choices", None))
    command_names = set(subparsers_action.choices.keys())

    assert "paper-cycle" in command_names
    assert "paper-review" in command_names
    assert "paper-summary" in command_names
    assert "research-brief" in command_names
    assert "memory-search" in command_names
    assert "memory-store-note" in command_names
    assert "review-closed-trades" in command_names
    assert "trade-reviews" in command_names
    assert "report" in command_names
    assert "env-check" in command_names
    assert "live-dry-run" in command_names
    assert "ibkr-diagnose" in command_names
    assert "buy" not in command_names
    assert "sell" not in command_names
    assert "order" not in command_names
    assert "orders" not in command_names
    assert "execute" not in command_names
    assert "brokerage" not in command_names
