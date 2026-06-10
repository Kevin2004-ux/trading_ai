from __future__ import annotations

import argparse
import json
from typing import Any

from diagnostics.healthcheck import check_environment
from diagnostics.live_dry_run import run_provider_dry_run
from providers.ibkr_provider import diagnose_ibkr_market_data_permissions
from jobs.paper_jobs import (
    run_daily_paper_review_job,
    run_paper_summary_job,
    run_weekly_paper_cycle_job,
)
from tools.agent_tools import (
    generate_report_tool,
    get_deep_research_brief_tool,
    get_trade_reviews_tool,
    review_closed_trades_tool,
    search_trade_memory_tool,
    store_trade_memory_tool,
)


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

    memory_search_parser = subparsers.add_parser(
        "memory-search",
        help="Search optional semantic trading memory.",
    )
    memory_search_parser.add_argument("--query", required=True)
    memory_search_parser.add_argument("--top-k", type=int, default=5)
    memory_search_parser.add_argument("--pretty", action="store_true")

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

    return parser


def _json_default(value: Any) -> str:
    return str(value)


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

    if args.command == "memory-search":
        return search_trade_memory_tool(query=args.query, top_k=args.top_k)

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
        getattr(args, "command", None) == "report"
        and getattr(args, "pretty", False)
        and getattr(args, "format", None) == "markdown"
        and bool(result.get("ok"))
    ):
        report = result.get("data", {})
        print(report.get("markdown", ""))
        return 0
    indent = 2 if getattr(args, "pretty", False) else None
    print(json.dumps(result, indent=indent, default=_json_default))
    return 0 if bool(result.get("ok")) else 1


if __name__ == "__main__":
    raise SystemExit(main())
