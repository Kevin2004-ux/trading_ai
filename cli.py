from __future__ import annotations

import argparse
import json
import os
from typing import Any

from config.runtime_readiness import check_runtime_readiness
from config.startup_validator import validate_startup_config
from diagnostics.healthcheck import check_environment
from diagnostics.live_dry_run import run_provider_dry_run
from db.audit_log import list_audit_events, verify_audit_chain
from db.checkpoints import list_recent_pipeline_runs
from db.schema_manager import apply_pending_migrations, get_schema_version, validate_schema
from analytics.filter_attribution import analyze_filter_attribution
from analytics.performance_attribution import analyze_paper_trade_performance
from analytics.strategy_diagnostics import diagnose_strategy_health
from analytics.trade_error_analysis import analyze_trade_errors
from analytics.timeframe_confirmation import evaluate_timeframe_confirmation
from analytics.volume_profile import build_volume_profile, evaluate_volume_profile_confirmation
from macro.calendar import get_macro_calendar
from macro.macro_risk import evaluate_macro_risk
from options.greeks_monitor import evaluate_option_greeks
from options.iv_rank import evaluate_iv_context
from options.options_risk import evaluate_option_trade_risk
from options.strategy_builder import build_option_strategy_candidates
from providers.ibkr_provider import diagnose_ibkr_market_data_permissions, diagnose_ibkr_option_quotes
from realtime.market_data import get_historical_bars
from realtime.options_chain import get_options_chain
from research.earnings_8k_analyzer import analyze_earnings_8k
from research.filing_analyzer import analyze_recent_filings
from research.filing_sentiment import evaluate_filing_sentiment
from research.news_provider import diagnose_news_provider, fetch_recent_news
from research.news_sentiment import evaluate_news_sentiment
from research.sec_edgar_provider import fetch_filing_text, fetch_recent_filings
from research.short_interest import evaluate_short_interest
from risk.concentration_controls import evaluate_concentration_risk
from risk.correlation_matrix import get_latest_correlation_snapshot, refresh_correlation_snapshot
from simulation.data_failure_simulator import (
    simulate_partial_scan_timeout,
    simulate_provider_outage,
    simulate_stale_data,
)
from simulation.portfolio_stress import stress_test_open_paper_trades
from simulation.scenario_definitions import get_stress_scenario, list_stress_scenarios
from simulation.scenario_runner import run_default_stress_suite
from simulation.stress_engine import run_stress_test_on_candidate
from jobs.paper_jobs import (
    run_daily_paper_review_job,
    run_paper_summary_job,
    run_weekly_paper_cycle_job,
)
from jobs.job_history import list_job_runs
from jobs.job_registry import list_registered_jobs
from jobs.job_runner import run_due_jobs, run_registered_job
from alerts.alert_manager import create_alert, list_alerts
from memory.annotation_store import (
    add_human_annotation,
    list_human_annotations,
    list_memory_retrieval_events,
    summarize_annotations,
)
from memory.retrieval_quality import evaluate_retrieval_quality
from memory.vector_memory import get_memory_config
from paper.paper_trader import get_paper_risk_diagnostics
from reports.report_generator import generate_performance_diagnostics_report
from tracking.trade_logger import get_candidate_decision_history, get_open_recommendations, get_trade_history
from tools.agent_tools import (
    generate_report_tool,
    get_deep_research_brief_tool,
    get_trade_reviews_tool,
    review_closed_trades_tool,
    search_trade_memory_tool,
    store_trade_memory_tool,
)
from translator.prompt_templates import build_gemini_system_prompt, build_weekly_trade_hunt_prompt
from translator.output_validator import validate_gemini_output
from translator.response_formatter import format_deterministic_fallback_response, format_validated_trade_response


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run simulated paper-trading workflows for the Trading AI app.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    paper_cycle_parser = subparsers.add_parser(
        "paper-cycle",
        help="Run the weekly simulated paper-trading cycle.",
    )
    paper_cycle_parser.add_argument("--universe", default="large_cap")
    paper_cycle_parser.add_argument("--max-tickers", type=int, default=500)
    paper_cycle_parser.add_argument("--max-trades", type=int, default=5)
    paper_cycle_parser.add_argument("--min-trades", type=int, default=2)
    paper_cycle_parser.add_argument(
        "--include-catalysts",
        dest="include_catalysts",
        action="store_true",
        default=True,
    )
    paper_cycle_parser.add_argument(
        "--no-include-catalysts",
        dest="include_catalysts",
        action="store_false",
    )
    paper_cycle_parser.add_argument(
        "--include-market-regime",
        dest="include_market_regime",
        action="store_true",
        default=True,
    )
    paper_cycle_parser.add_argument(
        "--no-include-market-regime",
        dest="include_market_regime",
        action="store_false",
    )
    paper_cycle_parser.add_argument(
        "--include-relative-strength",
        dest="include_relative_strength",
        action="store_true",
        default=True,
    )
    paper_cycle_parser.add_argument(
        "--no-include-relative-strength",
        dest="include_relative_strength",
        action="store_false",
    )
    paper_cycle_parser.add_argument(
        "--include-options",
        dest="include_options",
        action="store_true",
        default=False,
    )
    paper_cycle_parser.add_argument(
        "--no-include-options",
        dest="include_options",
        action="store_false",
    )
    paper_cycle_parser.add_argument(
        "--prefer-options",
        dest="prefer_options",
        action="store_true",
        default=False,
    )
    paper_cycle_parser.add_argument(
        "--no-prefer-options",
        dest="prefer_options",
        action="store_false",
    )
    paper_cycle_parser.add_argument("--max-option-contracts-per-trade", type=int, default=3)
    paper_cycle_parser.add_argument(
        "--include-portfolio-risk",
        dest="include_portfolio_risk",
        action="store_true",
        default=True,
    )
    paper_cycle_parser.add_argument(
        "--no-include-portfolio-risk",
        dest="include_portfolio_risk",
        action="store_false",
    )
    paper_cycle_parser.add_argument(
        "--include-position-sizing",
        dest="include_position_sizing",
        action="store_true",
        default=True,
    )
    paper_cycle_parser.add_argument(
        "--no-include-position-sizing",
        dest="include_position_sizing",
        action="store_false",
    )
    paper_cycle_parser.add_argument(
        "--include-memory-context",
        dest="include_memory_context",
        action="store_true",
        default=True,
    )
    paper_cycle_parser.add_argument(
        "--no-include-memory-context",
        dest="include_memory_context",
        action="store_false",
    )
    paper_cycle_parser.add_argument(
        "--store-memory",
        dest="store_memory",
        action="store_true",
        default=False,
    )
    paper_cycle_parser.add_argument(
        "--no-store-memory",
        dest="store_memory",
        action="store_false",
    )
    paper_cycle_parser.add_argument("--account-size", type=float, default=10000.0)
    paper_cycle_parser.add_argument("--risk-mode", default="normal")
    paper_cycle_parser.add_argument("--scan-max-concurrency", type=int, default=5)
    paper_cycle_parser.add_argument("--scan-ticker-timeout-seconds", type=float, default=15.0)
    paper_cycle_parser.add_argument("--scan-total-timeout-seconds", type=float, default=180.0)
    paper_cycle_parser.add_argument(
        "--disable-async-scan",
        dest="use_async_scan",
        action="store_false",
        default=True,
    )
    paper_cycle_parser.add_argument("--db-path", default="strategy_library.db")
    paper_cycle_parser.add_argument("--pretty", action="store_true")

    paper_review_parser = subparsers.add_parser(
        "paper-review",
        help="Review and update simulated paper-trading outcomes.",
    )
    paper_review_parser.add_argument(
        "--update-outcomes",
        dest="update_outcomes",
        action="store_true",
        default=True,
    )
    paper_review_parser.add_argument(
        "--no-update-outcomes",
        dest="update_outcomes",
        action="store_false",
    )
    paper_review_parser.add_argument(
        "--include-trade-reviews",
        dest="include_trade_reviews",
        action="store_true",
        default=True,
    )
    paper_review_parser.add_argument(
        "--no-include-trade-reviews",
        dest="include_trade_reviews",
        action="store_false",
    )
    paper_review_parser.add_argument(
        "--store-review-memory",
        dest="store_review_memory",
        action="store_true",
        default=False,
    )
    paper_review_parser.add_argument(
        "--no-store-review-memory",
        dest="store_review_memory",
        action="store_false",
    )
    paper_review_parser.add_argument("--db-path", default="strategy_library.db")
    paper_review_parser.add_argument("--pretty", action="store_true")

    paper_summary_parser = subparsers.add_parser(
        "paper-summary",
        help="Show the simulated paper-trading summary.",
    )
    paper_summary_parser.add_argument("--db-path", default="strategy_library.db")
    paper_summary_parser.add_argument("--pretty", action="store_true")

    research_brief_parser = subparsers.add_parser(
        "research-brief",
        help="Build a deterministic deep research brief for one ticker.",
    )
    research_brief_parser.add_argument("--ticker", required=True)
    research_brief_parser.add_argument(
        "--include-sec-filings",
        dest="include_sec_filings",
        action="store_true",
        default=True,
    )
    research_brief_parser.add_argument(
        "--no-include-sec-filings",
        dest="include_sec_filings",
        action="store_false",
    )
    research_brief_parser.add_argument(
        "--include-earnings-transcripts",
        dest="include_earnings_transcripts",
        action="store_true",
        default=True,
    )
    research_brief_parser.add_argument(
        "--no-include-earnings-transcripts",
        dest="include_earnings_transcripts",
        action="store_false",
    )
    research_brief_parser.add_argument(
        "--include-options",
        dest="include_options",
        action="store_true",
        default=False,
    )
    research_brief_parser.add_argument(
        "--no-include-options",
        dest="include_options",
        action="store_false",
    )
    research_brief_parser.add_argument("--db-path", default="strategy_library.db")
    research_brief_parser.add_argument("--pretty", action="store_true")

    sec_filings_parser = subparsers.add_parser(
        "sec-filings",
        help="Fetch recent SEC EDGAR filings for a ticker.",
    )
    sec_filings_parser.add_argument("--ticker", required=True)
    sec_filings_parser.add_argument("--limit", type=int, default=20)
    sec_filings_parser.add_argument("--pretty", action="store_true")

    filing_sentiment_parser = subparsers.add_parser(
        "filing-sentiment",
        help="Analyze recent SEC filings and deterministic filing sentiment for a ticker.",
    )
    filing_sentiment_parser.add_argument("--ticker", required=True)
    filing_sentiment_parser.add_argument("--limit", type=int, default=20)
    filing_sentiment_parser.add_argument("--pretty", action="store_true")

    earnings_8k_parser = subparsers.add_parser(
        "earnings-8k",
        help="Analyze the latest earnings-like 8-K for a ticker.",
    )
    earnings_8k_parser.add_argument("--ticker", required=True)
    earnings_8k_parser.add_argument("--pretty", action="store_true")

    short_interest_parser = subparsers.add_parser(
        "short-interest",
        help="Evaluate deterministic short-interest and squeeze-risk context for a ticker.",
    )
    short_interest_parser.add_argument("--ticker", required=True)
    short_interest_parser.add_argument("--short-percent-float", type=float)
    short_interest_parser.add_argument("--days-to-cover", type=float)
    short_interest_parser.add_argument("--borrow-rate", type=float)
    short_interest_parser.add_argument("--pretty", action="store_true")

    news_sentiment_parser = subparsers.add_parser(
        "news-sentiment",
        help="Fetch optional recent news and evaluate deterministic headline sentiment.",
    )
    news_sentiment_parser.add_argument("--ticker", required=True)
    news_sentiment_parser.add_argument("--limit", type=int, default=20)
    news_sentiment_parser.add_argument("--pretty", action="store_true")

    news_diagnostic_parser = subparsers.add_parser(
        "news-diagnostic",
        help="Diagnose optional news provider availability without placing trades.",
    )
    news_diagnostic_parser.add_argument("--pretty", action="store_true")

    memory_search_parser = subparsers.add_parser(
        "memory-search",
        help="Search optional semantic trading memory.",
    )
    memory_search_parser.add_argument("--query")
    memory_search_parser.add_argument("--ticker")
    memory_search_parser.add_argument("--setup")
    memory_search_parser.add_argument("--top-k", type=int, default=5)
    memory_search_parser.add_argument("--pretty", action="store_true")

    memory_status_parser = subparsers.add_parser(
        "memory-status",
        help="Show optional memory and retrieval quality readiness.",
    )
    memory_status_parser.add_argument("--db-path", default="strategy_library.db")
    memory_status_parser.add_argument("--pretty", action="store_true")

    annotate_trade_parser = subparsers.add_parser(
        "annotate-trade",
        help="Add a human annotation for a ticker, setup, trade, or decision.",
    )
    annotate_trade_parser.add_argument("--ticker")
    annotate_trade_parser.add_argument("--setup", dest="setup_type")
    annotate_trade_parser.add_argument("--entity-type", default="trade")
    annotate_trade_parser.add_argument("--entity-id")
    annotate_trade_parser.add_argument("--annotation-type", default="setup_review")
    annotate_trade_parser.add_argument("--rating", type=int)
    annotate_trade_parser.add_argument("--label")
    annotate_trade_parser.add_argument("--notes")
    annotate_trade_parser.add_argument("--db-path", default="strategy_library.db")
    annotate_trade_parser.add_argument("--pretty", action="store_true")

    annotations_parser = subparsers.add_parser(
        "annotations",
        help="List and summarize human annotations.",
    )
    annotations_parser.add_argument("--ticker")
    annotations_parser.add_argument("--setup", dest="setup_type")
    annotations_parser.add_argument("--limit", type=int, default=50)
    annotations_parser.add_argument("--db-path", default="strategy_library.db")
    annotations_parser.add_argument("--pretty", action="store_true")

    memory_events_parser = subparsers.add_parser(
        "memory-events",
        help="List recent memory retrieval events.",
    )
    memory_events_parser.add_argument("--limit", type=int, default=20)
    memory_events_parser.add_argument("--db-path", default="strategy_library.db")
    memory_events_parser.add_argument("--pretty", action="store_true")

    memory_store_parser = subparsers.add_parser(
        "memory-store-note",
        help="Store an optional qualitative trading memory note.",
    )
    memory_store_parser.add_argument("--ticker", required=True)
    memory_store_parser.add_argument("--note", required=True)
    memory_store_parser.add_argument("--pretty", action="store_true")

    review_closed_parser = subparsers.add_parser(
        "review-closed-trades",
        help="Build deterministic journal reviews for closed trades without reviews.",
    )
    review_closed_parser.add_argument(
        "--store-memory",
        dest="store_memory",
        action="store_true",
        default=False,
    )
    review_closed_parser.add_argument(
        "--no-store-memory",
        dest="store_memory",
        action="store_false",
    )
    review_closed_parser.add_argument("--db-path", default="strategy_library.db")
    review_closed_parser.add_argument("--pretty", action="store_true")

    trade_reviews_parser = subparsers.add_parser(
        "trade-reviews",
        help="Fetch deterministic journal reviews by ticker or recommendation id.",
    )
    trade_reviews_parser.add_argument("--ticker")
    trade_reviews_parser.add_argument("--recommendation-id", type=int)
    trade_reviews_parser.add_argument("--db-path", default="strategy_library.db")
    trade_reviews_parser.add_argument("--pretty", action="store_true")

    report_parser = subparsers.add_parser(
        "report",
        help="Generate deterministic trading system reports.",
    )
    report_parser.add_argument("--type", required=True, dest="report_type")
    report_parser.add_argument("--format", choices=["markdown", "dict"], default="markdown")
    report_parser.add_argument("--db-path", default="strategy_library.db")
    report_parser.add_argument("--pretty", action="store_true")

    performance_attribution_parser = subparsers.add_parser(
        "performance-attribution",
        help="Analyze simulated paper-trade performance attribution from SQLite.",
    )
    performance_attribution_parser.add_argument("--db-path", default="strategy_library.db")
    performance_attribution_parser.add_argument("--pretty", action="store_true")

    setup_diagnostics_parser = subparsers.add_parser(
        "setup-diagnostics",
        help="Diagnose setup-level paper-trading performance from SQLite.",
    )
    setup_diagnostics_parser.add_argument("--db-path", default="strategy_library.db")
    setup_diagnostics_parser.add_argument("--pretty", action="store_true")

    filter_attribution_parser = subparsers.add_parser(
        "filter-attribution",
        help="Analyze deterministic filter attribution from candidate history.",
    )
    filter_attribution_parser.add_argument("--db-path", default="strategy_library.db")
    filter_attribution_parser.add_argument("--pretty", action="store_true")

    trade_errors_parser = subparsers.add_parser(
        "trade-errors",
        help="Analyze deterministic paper-trade failure categories.",
    )
    trade_errors_parser.add_argument("--db-path", default="strategy_library.db")
    trade_errors_parser.add_argument("--pretty", action="store_true")

    stress_scenarios_parser = subparsers.add_parser(
        "stress-scenarios",
        help="List deterministic paper-trading stress scenarios.",
    )
    stress_scenarios_parser.add_argument("--pretty", action="store_true")

    stress_test_parser = subparsers.add_parser(
        "stress-test",
        help="Run one deterministic stress scenario against a sample paper candidate.",
    )
    stress_test_parser.add_argument("--scenario", required=True)
    stress_test_parser.add_argument("--pretty", action="store_true")

    stress_suite_parser = subparsers.add_parser(
        "stress-suite",
        help="Run the default deterministic stress-test suite without live API calls.",
    )
    stress_suite_parser.add_argument("--pretty", action="store_true")

    portfolio_stress_parser = subparsers.add_parser(
        "portfolio-stress",
        help="Stress-test currently open simulated paper trades from SQLite.",
    )
    portfolio_stress_parser.add_argument("--scenario", required=True)
    portfolio_stress_parser.add_argument("--db-path", default="strategy_library.db")
    portfolio_stress_parser.add_argument("--pretty", action="store_true")

    data_failure_parser = subparsers.add_parser(
        "data-failure-sim",
        help="Run deterministic data-failure simulations without provider calls.",
    )
    data_failure_parser.add_argument("--scenario", required=True)
    data_failure_parser.add_argument("--provider", default="ibkr")
    data_failure_parser.add_argument("--ticker", default="AAPL")
    data_failure_parser.add_argument("--pretty", action="store_true")

    performance_report_parser = subparsers.add_parser(
        "performance-report",
        help="Generate the paper performance diagnostics report.",
    )
    performance_report_parser.add_argument("--format", choices=["markdown", "dict"], default="markdown")
    performance_report_parser.add_argument("--db-path", default="strategy_library.db")
    performance_report_parser.add_argument("--pretty", action="store_true")

    env_check_parser = subparsers.add_parser(
        "env-check",
        help="Validate local dependencies, environment variables, startup imports, and SQLite initialization.",
    )
    env_check_parser.add_argument("--db-path", default="strategy_library.db")
    env_check_parser.add_argument("--pretty", action="store_true")

    live_dry_run_parser = subparsers.add_parser(
        "live-dry-run",
        help="Run a no-trade live provider availability dry run.",
    )
    live_dry_run_parser.add_argument("--ticker", default="AAPL")
    live_dry_run_parser.add_argument("--include-memory", action="store_true", default=False)
    live_dry_run_parser.add_argument("--db-path", default="strategy_library.db")
    live_dry_run_parser.add_argument("--pretty", action="store_true")

    ibkr_diagnose_parser = subparsers.add_parser(
        "ibkr-diagnose",
        help="Run a read-only IBKR market-data permission diagnostic.",
    )
    ibkr_diagnose_parser.add_argument("--ticker", default="AAPL")
    ibkr_diagnose_parser.add_argument("--pretty", action="store_true")

    ibkr_options_diagnose_parser = subparsers.add_parser(
        "ibkr-options-diagnose",
        help="Run a read-only IBKR option quote-chain diagnostic.",
    )
    ibkr_options_diagnose_parser.add_argument("--ticker", default="AAPL")
    ibkr_options_diagnose_parser.add_argument("--max-contracts", type=int, default=5)
    ibkr_options_diagnose_parser.add_argument("--pretty", action="store_true")

    risk_diagnostics_parser = subparsers.add_parser(
        "risk-diagnostics",
        help="Show paper-trading circuit breaker and setup decay diagnostics.",
    )
    risk_diagnostics_parser.add_argument("--db-path", default="strategy_library.db")
    risk_diagnostics_parser.add_argument("--pretty", action="store_true")

    macro_calendar_parser = subparsers.add_parser(
        "macro-calendar",
        help="Show the offline macro calendar used for risk controls.",
    )
    macro_calendar_parser.add_argument("--days", type=int, default=14)
    macro_calendar_parser.add_argument("--pretty", action="store_true")

    macro_risk_parser = subparsers.add_parser(
        "macro-risk",
        help="Evaluate current macro-event risk controls without live API calls.",
    )
    macro_risk_parser.add_argument("--pretty", action="store_true")

    correlation_refresh_parser = subparsers.add_parser(
        "correlation-refresh",
        help="Refresh and store a correlation matrix from historical bars.",
    )
    correlation_refresh_parser.add_argument("--tickers", nargs="+", required=True)
    correlation_refresh_parser.add_argument("--lookback-days", type=int, default=60)
    correlation_refresh_parser.add_argument("--db-path", default="strategy_library.db")
    correlation_refresh_parser.add_argument("--pretty", action="store_true")

    correlation_status_parser = subparsers.add_parser(
        "correlation-status",
        help="Show the latest stored correlation snapshot status.",
    )
    correlation_status_parser.add_argument("--max-age-hours", type=int, default=36)
    correlation_status_parser.add_argument("--db-path", default="strategy_library.db")
    correlation_status_parser.add_argument("--pretty", action="store_true")

    concentration_check_parser = subparsers.add_parser(
        "concentration-check",
        help="Evaluate concentration risk for a ticker against open recommendations.",
    )
    concentration_check_parser.add_argument("--ticker", required=True)
    concentration_check_parser.add_argument("--sector", default="unknown")
    concentration_check_parser.add_argument("--entry-price", type=float, default=100.0)
    concentration_check_parser.add_argument("--stop-loss", type=float, default=95.0)
    concentration_check_parser.add_argument("--target-price", type=float, default=110.0)
    concentration_check_parser.add_argument("--max-age-hours", type=int, default=36)
    concentration_check_parser.add_argument("--db-path", default="strategy_library.db")
    concentration_check_parser.add_argument("--pretty", action="store_true")

    volume_profile_parser = subparsers.add_parser(
        "volume-profile",
        help="Build an approximate daily close/volume profile for a ticker.",
    )
    volume_profile_parser.add_argument("--ticker", required=True)
    volume_profile_parser.add_argument("--lookback-days", type=int, default=90)
    volume_profile_parser.add_argument("--bins", type=int, default=24)
    volume_profile_parser.add_argument("--pretty", action="store_true")

    timeframe_check_parser = subparsers.add_parser(
        "timeframe-check",
        help="Evaluate daily/weekly timeframe confirmation for a ticker.",
    )
    timeframe_check_parser.add_argument("--ticker", required=True)
    timeframe_check_parser.add_argument("--lookback-days", type=int, default=180)
    timeframe_check_parser.add_argument("--pretty", action="store_true")

    iv_rank_parser = subparsers.add_parser(
        "iv-rank",
        help="Evaluate IV rank/percentile context for the first available option contract.",
    )
    iv_rank_parser.add_argument("--ticker", required=True)
    iv_rank_parser.add_argument("--pretty", action="store_true")

    greeks_check_parser = subparsers.add_parser(
        "greeks-check",
        help="Evaluate Greeks quality for the first available option contract.",
    )
    greeks_check_parser.add_argument("--ticker", required=True)
    greeks_check_parser.add_argument("--pretty", action="store_true")

    option_risk_check_parser = subparsers.add_parser(
        "option-risk-check",
        help="Evaluate IV, Greeks, DTE, and spread/fill risk for the first available option contract.",
    )
    option_risk_check_parser.add_argument("--ticker", required=True)
    option_risk_check_parser.add_argument("--pretty", action="store_true")

    option_strategies_parser = subparsers.add_parser(
        "option-strategies",
        help="Build and rank research-only option strategy candidates for a ticker.",
    )
    option_strategies_parser.add_argument("--ticker", required=True)
    option_strategies_parser.add_argument("--pretty", action="store_true")

    option_strategy_check_parser = subparsers.add_parser(
        "option-strategy-check",
        help="Build and inspect a specific option strategy candidate for a ticker.",
    )
    option_strategy_check_parser.add_argument("--ticker", required=True)
    option_strategy_check_parser.add_argument("--strategy", required=True)
    option_strategy_check_parser.add_argument("--pretty", action="store_true")

    db_status_parser = subparsers.add_parser(
        "db-status",
        help="Show SQLite schema, migration, pipeline, and audit status.",
    )
    db_status_parser.add_argument("--db-path", default="strategy_library.db")
    db_status_parser.add_argument("--pretty", action="store_true")

    db_migrate_parser = subparsers.add_parser(
        "db-migrate",
        help="Apply pending SQLite schema migrations.",
    )
    db_migrate_parser.add_argument("--db-path", default="strategy_library.db")
    db_migrate_parser.add_argument("--pretty", action="store_true")

    pipeline_runs_parser = subparsers.add_parser(
        "pipeline-runs",
        help="List recent pipeline runs.",
    )
    pipeline_runs_parser.add_argument("--limit", type=int, default=20)
    pipeline_runs_parser.add_argument("--db-path", default="strategy_library.db")
    pipeline_runs_parser.add_argument("--pretty", action="store_true")

    audit_log_parser = subparsers.add_parser(
        "audit-log",
        help="List recent immutable audit events.",
    )
    audit_log_parser.add_argument("--limit", type=int, default=100)
    audit_log_parser.add_argument("--run-id")
    audit_log_parser.add_argument("--db-path", default="strategy_library.db")
    audit_log_parser.add_argument("--pretty", action="store_true")

    config_check_parser = subparsers.add_parser(
        "config-check",
        help="Validate startup configuration without live provider calls.",
    )
    config_check_parser.add_argument("--db-path", default="strategy_library.db")
    config_check_parser.add_argument("--pretty", action="store_true")

    readiness_check_parser = subparsers.add_parser(
        "readiness-check",
        help="Check runtime readiness without live provider calls by default.",
    )
    readiness_check_parser.add_argument("--include-live-checks", action="store_true", default=False)
    readiness_check_parser.add_argument("--db-path", default="strategy_library.db")
    readiness_check_parser.add_argument("--pretty", action="store_true")

    jobs_parser = subparsers.add_parser(
        "jobs",
        help="List registered scheduled paper-trading jobs.",
    )
    jobs_parser.add_argument("--pretty", action="store_true")

    job_run_parser = subparsers.add_parser(
        "job-run",
        help="Run one registered scheduled job.",
    )
    job_run_parser.add_argument("--job", required=True)
    job_run_parser.add_argument("--dry-run", dest="dry_run", action="store_true", default=True)
    job_run_parser.add_argument("--no-dry-run", dest="dry_run", action="store_false")
    job_run_parser.add_argument("--db-path", default="strategy_library.db")
    job_run_parser.add_argument("--pretty", action="store_true")

    jobs_due_parser = subparsers.add_parser(
        "jobs-due",
        help="Run all currently due scheduled jobs.",
    )
    jobs_due_parser.add_argument("--dry-run", dest="dry_run", action="store_true", default=True)
    jobs_due_parser.add_argument("--no-dry-run", dest="dry_run", action="store_false")
    jobs_due_parser.add_argument("--now")
    jobs_due_parser.add_argument("--db-path", default="strategy_library.db")
    jobs_due_parser.add_argument("--pretty", action="store_true")

    job_history_parser = subparsers.add_parser(
        "job-history",
        help="List scheduled job run history.",
    )
    job_history_parser.add_argument("--limit", type=int, default=20)
    job_history_parser.add_argument("--db-path", default="strategy_library.db")
    job_history_parser.add_argument("--pretty", action="store_true")

    alerts_parser = subparsers.add_parser(
        "alerts",
        help="List local structured alert events.",
    )
    alerts_parser.add_argument("--limit", type=int, default=20)
    alerts_parser.add_argument("--severity")
    alerts_parser.add_argument("--db-path", default="strategy_library.db")
    alerts_parser.add_argument("--pretty", action="store_true")

    alert_test_parser = subparsers.add_parser(
        "alert-test",
        help="Create a local test alert without external sends.",
    )
    alert_test_parser.add_argument("--severity", default="warning")
    alert_test_parser.add_argument("--db-path", default="strategy_library.db")
    alert_test_parser.add_argument("--pretty", action="store_true")

    gemini_prompt_preview_parser = subparsers.add_parser(
        "gemini-prompt-preview",
        help="Preview structured Gemini prompts without calling Gemini.",
    )
    gemini_prompt_preview_parser.add_argument("--mode", default="weekly-trade-hunt")
    gemini_prompt_preview_parser.add_argument("--pretty", action="store_true")

    validate_gemini_parser = subparsers.add_parser(
        "validate-gemini-output",
        help="Validate a mocked Gemini output against a deterministic sample.",
    )
    validate_gemini_parser.add_argument("--sample", default="weekly-trade-hunt")
    validate_gemini_parser.add_argument("--pretty", action="store_true")

    format_response_parser = subparsers.add_parser(
        "format-trade-response",
        help="Format a deterministic sample response or validated Gemini response.",
    )
    format_response_parser.add_argument("--sample", default="weekly-trade-hunt")
    format_response_parser.add_argument("--pretty", action="store_true")

    return parser


def _json_default(value: Any) -> str:
    return str(value)


def _sec_cli_config() -> dict:
    return {"SEC_RESEARCH_ENABLED": "true"}


def _find_earnings_filing(filings: list[dict]) -> dict | None:
    for filing in filings:
        if not isinstance(filing, dict):
            continue
        items = " ".join(str(item) for item in filing.get("items", []) if item)
        description = str(filing.get("description", ""))
        if str(filing.get("form", "")).upper() == "8-K" and ("2.02" in items or "earnings" in description.lower()):
            return filing
    return None


def _build_filing_sentiment_payload(ticker: str, limit: int = 20) -> dict:
    normalized = str(ticker or "").upper()
    filings_result = fetch_recent_filings(
        normalized,
        forms=["8-K", "10-Q", "10-K"],
        limit=limit,
        config=_sec_cli_config(),
    )
    filings = filings_result.get("filings", []) if isinstance(filings_result, dict) else []
    analysis = analyze_recent_filings(normalized, filings)
    earnings_analysis = None
    earnings_filing = _find_earnings_filing(filings)
    if isinstance(earnings_filing, dict):
        text_result = fetch_filing_text(earnings_filing.get("filing_url"), config=_sec_cli_config()) if earnings_filing.get("filing_url") else {"ok": False}
        filing_text = text_result.get("text") if isinstance(text_result, dict) and text_result.get("ok") else earnings_filing.get("description", "")
        earnings_analysis = analyze_earnings_8k(normalized, earnings_filing, filing_text)
    sentiment = evaluate_filing_sentiment(normalized, analysis, earnings_analysis)
    errors = list(filings_result.get("errors", []) if isinstance(filings_result, dict) else [])
    return {
        "ok": bool(filings_result.get("ok")) if isinstance(filings_result, dict) else False,
        "ticker": normalized,
        "filings": filings_result,
        "filing_analysis": analysis,
        "earnings_8k_analysis": earnings_analysis,
        "filing_sentiment": sentiment,
        "warnings": list(filings_result.get("warnings", []) if isinstance(filings_result, dict) else []),
        "errors": errors,
    }


def _sample_weekly_trade_hunt_result() -> dict:
    return {
        "ok": True,
        "mode": "weekly_trade_hunt",
        "summary": {
            "selected_count": 1,
            "logged_count": 0,
            "message": "Built 1 final paper recommendation. Logged 0 recommendations.",
            "data_quality": {"warnings": ["Historical fallback enabled for one ticker."], "errors": []},
        },
        "market_regime": {"regime": "risk_on_uptrend", "summary": "Risk-on uptrend."},
        "decision_result": {
            "final_recommendations": [
                {
                    "ticker": "AAPL",
                    "asset_type": "stock",
                    "direction": "long",
                    "entry_price": 100.0,
                    "target_price": 112.0,
                    "stop_loss": 94.0,
                    "risk_reward": 2.0,
                    "thesis": "Passed deterministic momentum constraints.",
                    "risks": ["Historical fallback enabled for one ticker."],
                    "preferred_instrument": "stock",
                }
            ],
            "logged_recommendations": [],
            "not_selected": [{"ticker": "TSLA", "reason": "Rejected by concentration risk."}],
        },
        "selection_result": {
            "watchlist_alternatives": [{"ticker": "MSFT", "rejection_reason": "Watchlist only after technical warning."}],
            "rejected_candidates": [{"ticker": "TSLA", "rejection_reason": "Rejected by concentration risk."}],
        },
        "scan_result": {
            "data_quality_summary": {"warnings": ["Historical fallback enabled for one ticker."], "errors": []},
            "scan_execution_summary": {"warnings": []},
        },
        "option_risk_summary": {"blocked_count": 0},
    }


def _sample_valid_gemini_weekly_output() -> dict:
    return {
        "ok": True,
        "response_type": "weekly_trade_hunt",
        "paper_trading_only": True,
        "market_context": {"regime": "risk_on_uptrend"},
        "final_paper_trades": [
            {
                "ticker": "AAPL",
                "asset_type": "stock",
                "direction": "long",
                "entry_price": 100.0,
                "target_price": 112.0,
                "stop_loss": 94.0,
                "risk_reward": 2.0,
                "paper_logged": False,
            }
        ],
        "watchlist": [{"ticker": "MSFT", "reason": "Watchlist only after technical warning."}],
        "rejected_summary": [{"ticker": "TSLA", "reason": "Rejected by concentration risk."}],
        "options_status": {"status": "stock_only"},
        "risk_warnings": [],
        "data_quality_warnings": ["Historical fallback enabled for one ticker."],
        "plain_english_summary": "One paper-trading-only stock setup qualified. No trade was logged.",
        "errors": [],
    }


def run_command(args: argparse.Namespace) -> dict:
    if args.command == "paper-cycle":
        return run_weekly_paper_cycle_job(
            universe=args.universe,
            max_tickers=args.max_tickers,
            max_trades=args.max_trades,
            min_trades=args.min_trades,
            include_catalysts=args.include_catalysts,
            include_market_regime=args.include_market_regime,
            include_relative_strength=args.include_relative_strength,
            include_options=args.include_options,
            prefer_options=args.prefer_options,
            max_option_contracts_per_trade=args.max_option_contracts_per_trade,
            include_portfolio_risk=args.include_portfolio_risk,
            include_position_sizing=args.include_position_sizing,
            include_memory_context=args.include_memory_context,
            store_memory=args.store_memory,
            account_size=args.account_size,
            risk_mode=args.risk_mode,
            scan_max_concurrency=args.scan_max_concurrency,
            scan_ticker_timeout_seconds=args.scan_ticker_timeout_seconds,
            scan_total_timeout_seconds=args.scan_total_timeout_seconds,
            use_async_scan=args.use_async_scan,
            db_path=args.db_path,
        )

    if args.command == "paper-review":
        return run_daily_paper_review_job(
            update_outcomes=args.update_outcomes,
            include_trade_reviews=args.include_trade_reviews,
            store_review_memory=args.store_review_memory,
            db_path=args.db_path,
        )

    if args.command == "paper-summary":
        return run_paper_summary_job(db_path=args.db_path)

    if args.command == "research-brief":
        return get_deep_research_brief_tool(
            ticker=args.ticker,
            include_sec_filings=args.include_sec_filings,
            include_earnings_transcripts=args.include_earnings_transcripts,
            include_options=args.include_options,
            db_path=args.db_path,
        )

    if args.command == "sec-filings":
        return fetch_recent_filings(
            args.ticker,
            forms=["8-K", "10-Q", "10-K"],
            limit=args.limit,
            config=_sec_cli_config(),
        )

    if args.command == "filing-sentiment":
        return _build_filing_sentiment_payload(args.ticker, limit=args.limit)

    if args.command == "earnings-8k":
        filings_result = fetch_recent_filings(
            args.ticker,
            forms=["8-K"],
            limit=20,
            config=_sec_cli_config(),
        )
        filings = filings_result.get("filings", []) if isinstance(filings_result, dict) else []
        filing = _find_earnings_filing(filings)
        if not isinstance(filing, dict):
            return {
                "ok": False,
                "ticker": str(args.ticker or "").upper(),
                "filings": filings_result,
                "earnings_8k_analysis": None,
                "error": "No recent earnings-like 8-K was found.",
                "errors": ["No recent earnings-like 8-K was found."],
            }
        text_result = fetch_filing_text(filing.get("filing_url"), config=_sec_cli_config()) if filing.get("filing_url") else {"ok": False, "text": filing.get("description", "")}
        filing_text = text_result.get("text") if isinstance(text_result, dict) and text_result.get("ok") else filing.get("description", "")
        analysis = analyze_earnings_8k(args.ticker, filing, filing_text)
        return {
            "ok": bool(analysis.get("ok")),
            "ticker": str(args.ticker or "").upper(),
            "filing": filing,
            "filing_text": text_result,
            "earnings_8k_analysis": analysis,
            "errors": list(analysis.get("errors", [])),
        }

    if args.command == "short-interest":
        short_data = {
            "short_interest_percent_float": args.short_percent_float,
            "days_to_cover": args.days_to_cover,
            "borrow_rate": args.borrow_rate,
        }
        return evaluate_short_interest(args.ticker, short_data=short_data)

    if args.command == "news-sentiment":
        news = fetch_recent_news(
            args.ticker,
            limit=args.limit,
            config={"NEWS_RESEARCH_ENABLED": "true"},
        )
        articles = news.get("articles", []) if isinstance(news, dict) else []
        sentiment = evaluate_news_sentiment(args.ticker, articles)
        return {
            "ok": bool(news.get("ok")) if isinstance(news, dict) else False,
            "ticker": str(args.ticker or "").upper(),
            "news": news,
            "news_sentiment": sentiment,
            "warnings": list(news.get("warnings", []) if isinstance(news, dict) else []),
            "errors": list(news.get("errors", []) if isinstance(news, dict) else []),
        }

    if args.command == "news-diagnostic":
        return diagnose_news_provider()

    if args.command == "memory-search":
        query = args.query
        if not query:
            parts = [part for part in (args.ticker, args.setup) if part]
            query = " ".join(parts)
        if not query:
            return {"ok": False, "error": "Provide --query or --ticker/--setup for memory-search.", "errors": ["Missing memory search query."]}
        result = search_trade_memory_tool(query=query, top_k=args.top_k)
        retrieval = result.get("data") if isinstance(result, dict) else {}
        return {
            **result,
            "query": query,
            "retrieval_quality": evaluate_retrieval_quality(retrieval if isinstance(retrieval, dict) else {}),
        }

    if args.command == "memory-status":
        memory_config = get_memory_config()
        readiness = check_runtime_readiness({"DATABASE_PATH": args.db_path}, include_live_checks=False)
        return {
            "ok": True,
            "memory_enabled": str(os.getenv("MEMORY_ENABLED", "false")).lower() in {"1", "true", "yes", "y", "on"},
            "pinecone_memory_enabled": str(os.getenv("PINECONE_MEMORY_ENABLED", "false")).lower() in {"1", "true", "yes", "y", "on"},
            "pinecone_configured": bool(memory_config.get("pinecone_configured")),
            "pinecone_index_name": memory_config.get("pinecone_index_name"),
            "pinecone_namespace": memory_config.get("namespace"),
            "local_memory_fallback": str(os.getenv("LOCAL_MEMORY_FALLBACK", "true")).lower() in {"1", "true", "yes", "y", "on"},
            "retrieval_quality_gate_available": callable(evaluate_retrieval_quality),
            "annotation_store_available": True,
            "runtime_memory_ready": readiness.get("categories", {}).get("memory_ready"),
            "warnings": list(memory_config.get("warnings", [])),
            "errors": [],
        }

    if args.command == "annotate-trade":
        return add_human_annotation(
            db_path=args.db_path,
            entity_type=args.entity_type,
            annotation_type=args.annotation_type,
            rating=args.rating,
            label=args.label,
            notes=args.notes,
            entity_id=args.entity_id,
            ticker=args.ticker,
            setup_type=args.setup_type,
            payload={"source": "cli"},
        )

    if args.command == "annotations":
        listed = list_human_annotations(
            db_path=args.db_path,
            ticker=args.ticker,
            setup_type=args.setup_type,
            limit=args.limit,
        )
        summary = summarize_annotations(
            db_path=args.db_path,
            ticker=args.ticker,
            setup_type=args.setup_type,
        )
        return {
            "ok": bool(listed.get("ok")) and bool(summary.get("ok")),
            "annotations": listed,
            "summary": summary,
            "errors": [item for item in (listed.get("error"), summary.get("error")) if item],
        }

    if args.command == "memory-events":
        return list_memory_retrieval_events(db_path=args.db_path, limit=args.limit)

    if args.command == "memory-store-note":
        return store_trade_memory_tool(
            item={"ticker": args.ticker, "note": args.note, "tags": ["manual_note"]},
            item_type="manual_note",
        )

    if args.command == "review-closed-trades":
        return review_closed_trades_tool(
            db_path=args.db_path,
            store_memory=args.store_memory,
        )

    if args.command == "trade-reviews":
        return get_trade_reviews_tool(
            recommendation_id=args.recommendation_id,
            ticker=args.ticker,
            db_path=args.db_path,
        )

    if args.command == "report":
        return generate_report_tool(
            report_type=args.report_type,
            payload={},
            format=args.format,
            db_path=args.db_path,
        )

    if args.command == "performance-attribution":
        trades = get_trade_history(db_path=args.db_path)
        if isinstance(trades, dict) and trades.get("ok") is False:
            return {"ok": False, "errors": [trades.get("error", "Failed to load trade history.")]}
        return analyze_paper_trade_performance(trades if isinstance(trades, list) else [])

    if args.command == "setup-diagnostics":
        trades = get_trade_history(db_path=args.db_path)
        if isinstance(trades, dict) and trades.get("ok") is False:
            return {"ok": False, "errors": [trades.get("error", "Failed to load trade history.")]}
        return diagnose_strategy_health(trades if isinstance(trades, list) else [])

    if args.command == "filter-attribution":
        candidates = get_candidate_decision_history(db_path=args.db_path)
        trades = get_trade_history(db_path=args.db_path)
        if isinstance(candidates, dict) and candidates.get("ok") is False:
            return {"ok": False, "errors": [candidates.get("error", "Failed to load candidate history.")]}
        if isinstance(trades, dict) and trades.get("ok") is False:
            return {"ok": False, "errors": [trades.get("error", "Failed to load trade history.")]}
        return analyze_filter_attribution(candidates if isinstance(candidates, list) else [], trades=trades if isinstance(trades, list) else [])

    if args.command == "trade-errors":
        trades = get_trade_history(db_path=args.db_path)
        if isinstance(trades, dict) and trades.get("ok") is False:
            return {"ok": False, "errors": [trades.get("error", "Failed to load trade history.")]}
        return analyze_trade_errors(trades if isinstance(trades, list) else [])

    if args.command == "stress-scenarios":
        return list_stress_scenarios()

    if args.command == "stress-test":
        scenario = get_stress_scenario(args.scenario)
        if not scenario.get("ok"):
            return {
                "ok": False,
                "scenario": args.scenario,
                "error": "; ".join(scenario.get("errors", [])) or "Stress scenario not found.",
                "errors": scenario.get("errors", []),
            }
        sample_candidate = {
            "ticker": "AAPL",
            "asset_type": "stock",
            "direction": "long",
            "entry_price": 100.0,
            "target_price": 112.0,
            "stop_loss": 94.0,
            "risk_reward": 2.0,
            "recommendation_status": "recommendable",
            "passed": True,
        }
        return run_stress_test_on_candidate(sample_candidate, scenario["scenario"])

    if args.command == "stress-suite":
        return run_default_stress_suite()

    if args.command == "portfolio-stress":
        return stress_test_open_paper_trades(
            db_path=args.db_path,
            scenario_name=args.scenario,
        )

    if args.command == "data-failure-sim":
        scenario_name = str(args.scenario or "").strip().lower()
        if scenario_name == "provider_outage":
            return simulate_provider_outage([args.ticker], provider=args.provider)
        if scenario_name == "bad_data_stale_prices":
            return simulate_stale_data(
                {
                    "ok": True,
                    "ticker": str(args.ticker or "AAPL").upper(),
                    "source": "simulated",
                    "data": {"technical_snapshot": {"current_price": 100.0}},
                    "error": None,
                }
            )
        if scenario_name == "partial_scan_timeout":
            return simulate_partial_scan_timeout(
                {
                    "ok": True,
                    "best_candidates": [{"ticker": str(args.ticker or "AAPL").upper()}],
                    "scan_execution_summary": {"partial_results_used": False},
                }
            )
        return {
            "ok": False,
            "scenario": scenario_name,
            "error": "Unsupported data-failure simulation. Use provider_outage, bad_data_stale_prices, or partial_scan_timeout.",
            "errors": ["Unsupported data-failure simulation."],
        }

    if args.command == "performance-report":
        return generate_performance_diagnostics_report(db_path=args.db_path, format=args.format)

    if args.command == "env-check":
        return check_environment(db_path=args.db_path)

    if args.command == "live-dry-run":
        return run_provider_dry_run(
            ticker=args.ticker,
            include_memory=args.include_memory,
            db_path=args.db_path,
        )

    if args.command == "ibkr-diagnose":
        return diagnose_ibkr_market_data_permissions(ticker=args.ticker)

    if args.command == "ibkr-options-diagnose":
        return diagnose_ibkr_option_quotes(ticker=args.ticker, max_contracts=args.max_contracts)

    if args.command == "risk-diagnostics":
        return get_paper_risk_diagnostics(db_path=args.db_path)

    if args.command == "macro-calendar":
        from datetime import date, timedelta

        start = date.today()
        end = start + timedelta(days=max(int(args.days), 0))
        return get_macro_calendar(start_date=start.isoformat(), end_date=end.isoformat())

    if args.command == "macro-risk":
        return evaluate_macro_risk()

    if args.command == "correlation-refresh":
        return refresh_correlation_snapshot(
            db_path=args.db_path,
            tickers=args.tickers,
            price_history_provider=lambda ticker, lookback_days: get_historical_bars(ticker, lookback_days=lookback_days),
            lookback_days=args.lookback_days,
        )

    if args.command == "correlation-status":
        return get_latest_correlation_snapshot(db_path=args.db_path, max_age_hours=args.max_age_hours)

    if args.command == "concentration-check":
        latest = get_latest_correlation_snapshot(db_path=args.db_path, max_age_hours=args.max_age_hours)
        snapshot = latest.get("snapshot") if isinstance(latest, dict) else None
        matrix = {
            "correlations": snapshot.get("matrix_json", {}),
            "tickers": snapshot.get("tickers_json", []),
        } if isinstance(snapshot, dict) else None
        open_trades = get_open_recommendations(db_path=args.db_path)
        if not isinstance(open_trades, list):
            open_trades = []
        candidate = {
            "ticker": args.ticker,
            "asset_type": "stock",
            "direction": "long",
            "sector": args.sector,
            "entry_price": args.entry_price,
            "stop_loss": args.stop_loss,
            "target_price": args.target_price,
        }
        result = evaluate_concentration_risk(candidate, open_trades=open_trades, correlation_matrix=matrix)
        return {
            "ok": bool(result.get("ok")),
            "ticker": str(args.ticker).upper(),
            "latest_correlation_snapshot": latest,
            "concentration_risk": result,
            "errors": [] if result.get("ok") else [result.get("error", "Concentration check failed.")],
        }

    if args.command == "volume-profile":
        historical = get_historical_bars(args.ticker, lookback_days=args.lookback_days)
        bars = ((historical.get("data") or {}).get("bars") if isinstance(historical, dict) else None) or []
        profile = build_volume_profile(bars, bins=args.bins, lookback_days=args.lookback_days)
        candidate = {"ticker": args.ticker, "current_price": bars[-1].get("close") if bars else None, "direction": "long"}
        confirmation = evaluate_volume_profile_confirmation(candidate, bars, config={"bins": args.bins, "lookback_days": args.lookback_days})
        return {
            "ok": bool(profile.get("ok")) or bool(confirmation.get("ok")),
            "ticker": str(args.ticker).upper(),
            "historical_bars": historical,
            "volume_profile": profile,
            "confirmation": confirmation,
            "errors": list(profile.get("errors", [])),
        }

    if args.command == "timeframe-check":
        historical = get_historical_bars(args.ticker, lookback_days=args.lookback_days)
        bars = ((historical.get("data") or {}).get("bars") if isinstance(historical, dict) else None) or []
        candidate = {"ticker": args.ticker, "current_price": bars[-1].get("close") if bars else None, "direction": "long"}
        confirmation = evaluate_timeframe_confirmation(candidate, bars, weekly_history=None)
        return {
            "ok": bool(confirmation.get("ok")),
            "ticker": str(args.ticker).upper(),
            "historical_bars": historical,
            "timeframe_confirmation": confirmation,
            "errors": [] if confirmation.get("ok") else list((confirmation.get("features") or {}).get("errors", [])),
        }

    if args.command in {"iv-rank", "greeks-check", "option-risk-check"}:
        chain = get_options_chain(args.ticker)
        contracts = ((chain.get("data") or {}).get("contracts") if isinstance(chain, dict) else None) or []
        first_contract = next((item for item in contracts if isinstance(item, dict)), None)
        if not first_contract:
            return {
                "ok": False,
                "ticker": str(args.ticker).upper(),
                "options_chain": chain,
                "error": (chain.get("error") if isinstance(chain, dict) else None) or "No option contract with quote, IV, and Greeks data is available.",
                "errors": [(chain.get("error") if isinstance(chain, dict) else None) or "No option contract with quote, IV, and Greeks data is available."],
            }
        if args.command == "iv-rank":
            iv_context = evaluate_iv_context(
                first_contract.get("implied_volatility") or first_contract.get("iv"),
                config={
                    "iv_rank": first_contract.get("iv_rank"),
                    "iv_percentile": first_contract.get("iv_percentile"),
                },
            )
            return {
                "ok": bool(iv_context.get("ok")),
                "ticker": str(args.ticker).upper(),
                "option_contract": first_contract.get("option_contract"),
                "iv_context": iv_context,
                "errors": list(iv_context.get("errors", [])),
            }
        if args.command == "greeks-check":
            greeks = evaluate_option_greeks(first_contract)
            return {
                "ok": bool(greeks.get("ok")),
                "ticker": str(args.ticker).upper(),
                "option_contract": first_contract.get("option_contract"),
                "greeks_monitoring": greeks,
                "errors": list(greeks.get("errors", [])),
            }
        option_risk = evaluate_option_trade_risk(first_contract)
        return {
            "ok": bool(option_risk.get("approved")),
            "ticker": str(args.ticker).upper(),
            "option_contract": first_contract.get("option_contract"),
            "option_trade_risk": option_risk,
            "errors": list(option_risk.get("errors", [])),
        }

    if args.command in {"option-strategies", "option-strategy-check"}:
        chain = get_options_chain(args.ticker)
        contracts = ((chain.get("data") or {}).get("contracts") if isinstance(chain, dict) else None) or []
        if not contracts:
            return {
                "ok": False,
                "ticker": str(args.ticker).upper(),
                "options_chain": chain,
                "strategy_result": None,
                "error": (chain.get("error") if isinstance(chain, dict) else None) or "No option chain quotes are available for strategy research.",
                "errors": [(chain.get("error") if isinstance(chain, dict) else None) or "No option chain quotes are available for strategy research."],
            }
        result = build_option_strategy_candidates(
            str(args.ticker).upper(),
            {"ticker": args.ticker, "current_price": contracts[0].get("underlying_price") or 0.0, "option_bias": "bullish"},
            contracts,
        )
        if args.command == "option-strategy-check":
            requested = str(args.strategy).lower()
            matches = [item for item in result.get("strategies", []) if str(item.get("strategy_type", "")).lower() == requested]
            if not matches:
                return {
                    "ok": False,
                    "ticker": str(args.ticker).upper(),
                    "strategy": requested,
                    "strategy_result": result,
                    "error": f"No {requested} strategy could be built from the available option chain.",
                    "errors": [f"No {requested} strategy could be built from the available option chain."],
                }
            return {
                "ok": True,
                "ticker": str(args.ticker).upper(),
                "requested_strategy": requested,
                "strategy": matches[0],
                "strategy_result": result,
                "errors": [],
            }
        return {
            "ok": bool(result.get("ok")),
            "ticker": str(args.ticker).upper(),
            "strategy_result": result,
            "errors": list(result.get("errors", [])),
        }

    if args.command == "db-migrate":
        return apply_pending_migrations(db_path=args.db_path)

    if args.command == "db-status":
        schema = get_schema_version(db_path=args.db_path)
        validation = validate_schema(db_path=args.db_path)
        audit = verify_audit_chain(db_path=args.db_path)
        runs = list_recent_pipeline_runs(db_path=args.db_path, limit=20)
        return {
            "ok": bool(validation.get("ok")) and bool(audit.get("ok")),
            "db_path": args.db_path,
            "schema_version": schema,
            "validation": validation,
            "recent_pipeline_runs_count": runs.get("count", 0),
            "audit_chain": audit,
            "errors": list(validation.get("errors", [])) + list(audit.get("errors", [])),
        }

    if args.command == "pipeline-runs":
        return list_recent_pipeline_runs(db_path=args.db_path, limit=args.limit)

    if args.command == "audit-log":
        return list_audit_events(db_path=args.db_path, run_id=args.run_id, limit=args.limit)

    if args.command == "config-check":
        return validate_startup_config({"DATABASE_PATH": args.db_path})

    if args.command == "readiness-check":
        return check_runtime_readiness({"DATABASE_PATH": args.db_path}, include_live_checks=args.include_live_checks)

    if args.command == "jobs":
        return list_registered_jobs()

    if args.command == "job-run":
        return run_registered_job(
            args.job,
            db_path=args.db_path,
            dry_run=args.dry_run,
        )

    if args.command == "jobs-due":
        return run_due_jobs(
            db_path=args.db_path,
            now=args.now,
            dry_run=args.dry_run,
        )

    if args.command == "job-history":
        return list_job_runs(db_path=args.db_path, limit=args.limit)

    if args.command == "alerts":
        return list_alerts(db_path=args.db_path, limit=args.limit, severity=args.severity)

    if args.command == "alert-test":
        return create_alert(
            db_path=args.db_path,
            severity=args.severity,
            alert_type="test_alert",
            title="Local test alert",
            message="This is a local structured test alert. No external notification was sent.",
            payload={"source": "cli", "external_send": False},
            source="cli",
        )

    if args.command == "gemini-prompt-preview":
        sample = _sample_weekly_trade_hunt_result()
        prompt = build_weekly_trade_hunt_prompt("Find weekly paper trades.", sample)
        return {
            "ok": True,
            "mode": args.mode,
            "system_prompt": build_gemini_system_prompt(),
            "prompt": prompt,
            "errors": [],
        }

    if args.command == "validate-gemini-output":
        sample = _sample_weekly_trade_hunt_result()
        output = _sample_valid_gemini_weekly_output()
        validation = validate_gemini_output(output, sample)
        return {
            "ok": bool(validation.get("ok")),
            "sample": args.sample,
            "validation": validation,
            "errors": list(validation.get("errors", [])),
        }

    if args.command == "format-trade-response":
        sample = _sample_weekly_trade_hunt_result()
        validation = validate_gemini_output(_sample_valid_gemini_weekly_output(), sample)
        return {
            "ok": True,
            "sample": args.sample,
            "validated_response": format_validated_trade_response(validation, fallback_result=sample),
            "fallback_response": format_deterministic_fallback_response(sample),
            "validation": validation,
            "errors": [],
        }

    return {
        "ok": False,
        "command": args.command,
        "error": f"Unsupported command: {args.command}",
    }


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    result = run_command(args)
    if (
        getattr(args, "command", None) in {"report", "performance-report"}
        and getattr(args, "pretty", False)
        and getattr(args, "format", None) == "markdown"
        and bool(result.get("ok"))
    ):
        report = result.get("data", {}) if getattr(args, "command", None) == "report" else result
        print(report.get("markdown", ""))
        return 0
    indent = 2 if getattr(args, "pretty", False) else None
    print(json.dumps(result, indent=indent, default=_json_default))
    return 0 if bool(result.get("ok")) else 1


if __name__ == "__main__":
    raise SystemExit(main())
