from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from journal.trade_journal import get_trade_reviews
from tracking.trade_logger import (
    get_open_recommendations,
    get_strategy_performance,
    get_win_loss_record,
)


SUPPORTED_FORMATS = {"markdown", "dict"}
SIMULATION_WARNING = "Paper-trading results are simulated only and are not live brokerage P/L."


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _is_ok(payload: Any) -> bool:
    return isinstance(payload, dict) and bool(payload.get("ok"))


def _safe_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _normalize_format(fmt: str) -> str:
    return str(fmt or "markdown").strip().lower()


def _coalesce_dict(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def _coalesce_list(value: Any) -> list:
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return []


def _bullet_lines(items: list[str]) -> str:
    lines = [f"- {item}" for item in items if str(item).strip()]
    return "\n".join(lines) if lines else "- None"


def _fmt_num(value: Any, digits: int = 2) -> str:
    number = _safe_float(value)
    if number is None:
        return "N/A"
    return f"{number:.{digits}f}"


def _fmt_price(value: Any) -> str:
    number = _safe_float(value)
    if number is None:
        return "N/A"
    return f"${number:.2f}"


def _section(title: str, body: str, data: Any = None) -> dict:
    return {
        "title": title,
        "body": body,
        "data": data,
    }


def _report_error(report_type: str, fmt: str, error: str) -> dict:
    return {
        "ok": False,
        "timestamp": _now_iso(),
        "report_type": report_type,
        "format": fmt,
        "title": "",
        "summary": "",
        "sections": [],
        "markdown": "",
        "data_quality": {
            "missing_sections": [],
            "warnings": [],
        },
        "error": error,
    }


def _finalize_report(
    *,
    report_type: str,
    fmt: str,
    title: str,
    summary: str,
    sections: list[dict],
    missing_sections: list[str] | None = None,
    warnings: list[str] | None = None,
) -> dict:
    normalized_format = _normalize_format(fmt)
    if normalized_format not in SUPPORTED_FORMATS:
        return _report_error(report_type, normalized_format, f"Unsupported report format: {fmt}")

    missing = [item for item in (missing_sections or []) if item]
    warning_items = [item for item in (warnings or []) if item]
    markdown_parts = [f"# {title}", "", summary]
    for section in sections:
        markdown_parts.extend(["", f"## {section['title']}", "", section["body"]])
    if missing or warning_items:
        markdown_parts.extend(["", "## Data Quality", ""])
        if missing:
            markdown_parts.append("Missing sections:")
            markdown_parts.append(_bullet_lines(missing))
        if warning_items:
            markdown_parts.append("Warnings:")
            markdown_parts.append(_bullet_lines(warning_items))

    return {
        "ok": True,
        "timestamp": _now_iso(),
        "report_type": report_type,
        "format": normalized_format,
        "title": title,
        "summary": summary,
        "sections": sections,
        "markdown": "\n".join(markdown_parts).strip(),
        "data_quality": {
            "missing_sections": missing,
            "warnings": warning_items,
        },
        "error": None,
    }


def _decision_trade_lines(trade: dict) -> list[str]:
    risks = trade.get("risks") if isinstance(trade.get("risks"), list) else []
    position_sizing = _coalesce_dict(trade.get("position_sizing"))
    portfolio_risk = _coalesce_dict(trade.get("portfolio_risk"))
    option_context = _coalesce_dict(trade.get("preferred_option_mispricing_context"))
    lines = [
        f"Ticker: {trade.get('ticker', 'N/A')}",
        f"Asset type: {trade.get('asset_type', 'stock')}",
        f"Direction: {trade.get('direction', 'N/A')}",
        f"Setup type: {trade.get('setup_type', 'N/A')}",
        f"Entry: {_fmt_price(trade.get('entry_price'))}",
        f"Target: {_fmt_price(trade.get('target_price'))}",
        f"Stop: {_fmt_price(trade.get('stop_loss'))}",
        f"Risk/reward: {_fmt_num(trade.get('risk_reward'))}",
        f"Position sizing: {position_sizing if position_sizing else 'N/A'}",
        f"Portfolio risk notes: {portfolio_risk.get('summary') or portfolio_risk.get('decision') or 'N/A'}",
        f"Thesis: {trade.get('thesis') or trade.get('research_summary') or 'N/A'}",
        f"Invalidation: {trade.get('invalidation') or 'N/A'}",
        f"Key risks: {', '.join(risks) if risks else 'N/A'}",
    ]
    if trade.get("preferred_option_contract"):
        lines.append(f"Preferred option: {trade.get('preferred_option_contract')}")
    elif isinstance(trade.get("option_alternatives"), list) and trade["option_alternatives"]:
        lines.append(f"Option alternative: {trade['option_alternatives'][0].get('option_contract', 'N/A')}")
    if option_context:
        lines.append(f"Option context: {option_context.get('mispricing_label') or option_context}")
    if trade.get("similar_setup_context"):
        lines.append("Memory/research notes: Similar setup context was attached.")
    return lines


def generate_weekly_trade_plan_report(
    trade_hunt_result: dict,
    format: str = "markdown",
) -> dict:
    payload = _coalesce_dict(trade_hunt_result)
    if not payload:
        return _report_error("weekly_trade_plan", _normalize_format(format), "trade_hunt_result is required.")

    decision_result = _coalesce_dict(payload.get("decision_result"))
    selection_result = _coalesce_dict(payload.get("selection_result"))
    market_regime = _coalesce_dict(payload.get("market_regime"))
    portfolio_risk = _coalesce_dict(payload.get("portfolio_risk"))
    selected_trades = _coalesce_list(decision_result.get("final_recommendations"))
    watchlist = _coalesce_list(selection_result.get("watchlist_alternatives"))
    risk_rejected = _coalesce_list(decision_result.get("risk_rejected"))
    rejected = _coalesce_list(selection_result.get("rejected_candidates")) + _coalesce_list(decision_result.get("not_selected"))
    warnings = [SIMULATION_WARNING]
    missing: list[str] = []

    if not selected_trades:
        missing.append("selected_trades")
    if not market_regime:
        missing.append("market_regime")
    if not portfolio_risk:
        missing.append("portfolio_risk")

    selected_body = "\n\n".join(
        [f"### {trade.get('ticker', 'Unknown')}\n" + _bullet_lines(_decision_trade_lines(trade)) for trade in selected_trades]
    ) or "No final trades were selected."

    watchlist_body = _bullet_lines(
        [
            f"{candidate.get('ticker', 'Unknown')}: {candidate.get('rejection_reason') or candidate.get('recommendation_status') or 'Watchlist'}"
            for candidate in watchlist
        ]
    )
    rejected_body = _bullet_lines(
        [
            f"{item.get('ticker') or _coalesce_dict(item.get('candidate')).get('ticker', 'Unknown')}: {item.get('reason') or item.get('rejection_reason') or 'Rejected'}"
            for item in (risk_rejected + rejected)
            if isinstance(item, dict)
        ]
    )
    option_body = _bullet_lines(
        [
            f"{trade.get('ticker', 'Unknown')}: {trade.get('preferred_option_contract') or (_coalesce_list(trade.get('option_alternatives'))[0].get('option_contract') if _coalesce_list(trade.get('option_alternatives')) else 'No option alternative')}"
            for trade in selected_trades
        ]
    )
    regime_summary = market_regime.get("summary") or market_regime.get("regime") or "Market regime summary unavailable."
    risk_summary = _coalesce_dict(portfolio_risk.get("risk_summary")).get("message") or "Portfolio risk summary unavailable."
    sizing_body = _bullet_lines(
        [
            f"{trade.get('ticker', 'Unknown')}: {trade.get('position_sizing') or 'No sizing attached'}"
            for trade in selected_trades
        ]
    )
    notes_body = _bullet_lines(
        [
            f"{trade.get('ticker', 'Unknown')}: {trade.get('research_summary') or trade.get('thesis') or 'No research note attached'}"
            for trade in selected_trades
        ]
    )
    final_warning_body = _bullet_lines(
        [
            SIMULATION_WARNING,
            "Reports summarize deterministic system output and do not create new trades by themselves.",
            *(_coalesce_list(payload.get("errors"))[:5]),
        ]
    )

    sections = [
        _section("Market Regime", regime_summary, market_regime),
        _section("Selected Trades", selected_body, selected_trades),
        _section("Watchlist Alternatives", watchlist_body, watchlist),
        _section("Rejected Or Risk-Rejected", rejected_body, {"risk_rejected": risk_rejected, "rejected": rejected}),
        _section("Option Alternatives", option_body, selected_trades),
        _section("Portfolio Risk", risk_summary, portfolio_risk),
        _section("Position Sizing", sizing_body, selected_trades),
        _section("Research And Memory Notes", notes_body, selected_trades),
        _section("Final Warnings", final_warning_body, {"warnings": warnings}),
    ]
    summary = payload.get("summary", {}).get("message") or f"Weekly plan includes {len(selected_trades)} selected trades."
    return _finalize_report(
        report_type="weekly_trade_plan",
        fmt=format,
        title="Weekly Trade Plan",
        summary=summary,
        sections=sections,
        missing_sections=missing,
        warnings=warnings,
    )


def generate_open_trade_review_report(
    paper_review_result: dict,
    format: str = "markdown",
) -> dict:
    payload = _coalesce_dict(paper_review_result)
    if not payload:
        return _report_error("open_trade_review", _normalize_format(format), "paper_review_result is required.")

    open_trades = _coalesce_list(payload.get("open_paper_trades"))
    newly_closed = _coalesce_list(payload.get("recently_closed_paper_trades"))
    win_loss_record = _coalesce_dict(payload.get("win_loss_record"))
    trade_review_summary = _coalesce_dict(payload.get("trade_review_summary"))
    monitoring_result = _coalesce_dict(payload.get("monitoring_result"))
    update_result = _coalesce_dict(monitoring_result.get("update_result"))
    manual_review_items = [
        item for item in _coalesce_list(update_result.get("results"))
        if isinstance(item, dict) and str(item.get("outcome", "")).lower() == "manual_review"
    ]
    warnings = [SIMULATION_WARNING]
    missing: list[str] = []

    if not open_trades:
        missing.append("open_trades")
    if not win_loss_record:
        missing.append("win_loss_record")

    sections = [
        _section(
            "Open Trades",
            _bullet_lines(
                [
                    f"{trade.get('ticker', 'Unknown')}: status={trade.get('status', 'open')}, entry={_fmt_price(trade.get('entry_price'))}, target={_fmt_price(trade.get('target_price'))}, stop={_fmt_price(trade.get('stop_loss'))}"
                    for trade in open_trades
                ]
            ),
            open_trades,
        ),
        _section(
            "Newly Closed Trades",
            _bullet_lines(
                [
                    f"{trade.get('ticker', 'Unknown')}: outcome={trade.get('outcome', 'unknown')}, exit={_fmt_price(trade.get('exit_price'))}"
                    for trade in newly_closed
                ]
            ),
            newly_closed,
        ),
        _section(
            "Win/Loss Record",
            _bullet_lines(
                [
                    f"Wins: {win_loss_record.get('wins', 0)}",
                    f"Losses: {win_loss_record.get('losses', 0)}",
                    f"Expired: {win_loss_record.get('expired', 0)}",
                    f"Open: {win_loss_record.get('open', 0)}",
                    f"Win rate: {_fmt_num(win_loss_record.get('win_rate'))}%",
                ]
            ),
            win_loss_record,
        ),
        _section(
            "Trade Review Summary",
            _bullet_lines(
                [
                    f"Reviewed count: {trade_review_summary.get('reviewed_count', 0)}",
                    f"Skipped count: {trade_review_summary.get('skipped_count', 0)}",
                ]
            ) if trade_review_summary else "No trade review summary available.",
            trade_review_summary,
        ),
        _section(
            "Manual Review Needed",
            _bullet_lines(
                [
                    f"{item.get('ticker', 'Unknown')}: {item.get('exit_reason') or item.get('error') or 'Manual review required'}"
                    for item in manual_review_items
                ]
            ),
            manual_review_items,
        ),
        _section(
            "Next Actions",
            _bullet_lines(
                [
                    "Check open trades against updated stops and targets.",
                    "Inspect any manual-review outcomes before trusting performance summaries.",
                    "Review newly closed trades for lessons if journal reviews were created.",
                ]
            ),
        ),
    ]
    summary = payload.get("warning") or f"Open review covers {len(open_trades)} open trades and {len(newly_closed)} newly closed trades."
    return _finalize_report(
        report_type="open_trade_review",
        fmt=format,
        title="Open Trade Review",
        summary=summary,
        sections=sections,
        missing_sections=missing,
        warnings=warnings,
    )


def generate_performance_report(
    performance_data: dict,
    format: str = "markdown",
) -> dict:
    payload = _coalesce_dict(performance_data)
    if not payload:
        return _report_error("performance", _normalize_format(format), "performance_data is required.")

    win_loss_record = _coalesce_dict(payload.get("win_loss_record") or payload)
    strategy_performance = _coalesce_dict(payload.get("strategy_performance"))
    setup_performance = payload.get("setup_performance")
    warnings = [SIMULATION_WARNING]
    missing: list[str] = []

    if not win_loss_record:
        missing.append("win_loss_record")
    if not strategy_performance:
        missing.append("strategy_performance")
    if not setup_performance:
        missing.append("setup_performance")

    by_setup_type = _coalesce_list(strategy_performance.get("by_setup_type"))
    ranked = [item for item in by_setup_type if _safe_float(item.get("average_realized_return")) is not None]
    ranked.sort(key=lambda item: float(item["average_realized_return"]), reverse=True)
    best_setup = ranked[0] if ranked else {}
    worst_setup = ranked[-1] if ranked else {}

    expectancy_value = None
    if isinstance(setup_performance, dict):
        expectancy_value = _safe_float(setup_performance.get("expectancy"))
    elif isinstance(setup_performance, list):
        expectancy_values = [_safe_float(item.get("expectancy")) for item in setup_performance if isinstance(item, dict)]
        expectancy_values = [value for value in expectancy_values if value is not None]
        if expectancy_values:
            expectancy_value = sum(expectancy_values) / len(expectancy_values)

    sections = [
        _section(
            "Win/Loss Record",
            _bullet_lines(
                [
                    f"Total recommendations: {win_loss_record.get('total_recommendations', 0)}",
                    f"Closed trades: {win_loss_record.get('closed_trades', 0)}",
                    f"Open trades: {win_loss_record.get('open', 0)}",
                    f"Wins: {win_loss_record.get('wins', 0)}",
                    f"Losses: {win_loss_record.get('losses', 0)}",
                    f"Win rate: {_fmt_num(win_loss_record.get('win_rate'))}%",
                ]
            ),
            win_loss_record,
        ),
        _section(
            "Strategy Performance",
            _bullet_lines(
                [
                    f"{item.get('strategy', 'unknown')}: total={item.get('total_recommendations', 0)}, avg_return={_fmt_num(item.get('average_realized_return'))}%"
                    for item in _coalesce_list(strategy_performance.get("by_strategy"))
                ]
            ),
            strategy_performance,
        ),
        _section(
            "Setup Performance",
            _bullet_lines(
                [
                    f"{item.get('setup_type', 'unspecified')}: total={item.get('total_recommendations', 0)}, avg_return={_fmt_num(item.get('average_realized_return'))}%"
                    for item in by_setup_type
                ]
            ),
            by_setup_type,
        ),
        _section(
            "Best And Worst Setups",
            _bullet_lines(
                [
                    f"Best setup: {best_setup.get('setup_type', 'N/A')} ({_fmt_num(best_setup.get('average_realized_return'))}%)",
                    f"Worst setup: {worst_setup.get('setup_type', 'N/A')} ({_fmt_num(worst_setup.get('average_realized_return'))}%)",
                    f"Expectancy: {_fmt_num(expectancy_value)}",
                ]
            ),
            {"best_setup": best_setup, "worst_setup": worst_setup, "expectancy": expectancy_value},
        ),
        _section(
            "Simulation Warning",
            _bullet_lines([SIMULATION_WARNING]),
        ),
    ]
    summary = f"Performance report shows a { _fmt_num(win_loss_record.get('win_rate')) }% win rate across simulated trades."
    return _finalize_report(
        report_type="performance",
        fmt=format,
        title="Performance Report",
        summary=summary,
        sections=sections,
        missing_sections=missing,
        warnings=warnings,
    )


def generate_ticker_research_memo(
    research_brief: dict,
    format: str = "markdown",
) -> dict:
    payload = _coalesce_dict(research_brief)
    if not payload:
        return _report_error("ticker_research", _normalize_format(format), "research_brief is required.")

    warnings = [item for item in _coalesce_list(_coalesce_dict(payload.get("data_quality")).get("stale_data_flags"))]
    missing = _coalesce_list(_coalesce_dict(payload.get("data_quality")).get("missing_sections"))
    evidence_table = _coalesce_list(payload.get("evidence_table"))
    option_context = _coalesce_dict(payload.get("options_context"))
    filing_context = _coalesce_dict(payload.get("filing_context"))
    transcript_context = _coalesce_dict(payload.get("earnings_transcript_context"))

    sections = [
        _section("Research Summary", str(payload.get("research_summary") or "Research summary unavailable."), payload.get("research_summary")),
        _section("Trade Thesis", str(_coalesce_dict(payload.get("trade_thesis")).get("thesis") or "Trade thesis unavailable."), payload.get("trade_thesis")),
        _section("Bull Case", _bullet_lines([str(point) for point in _coalesce_list(_coalesce_dict(payload.get("bull_case")).get("points"))]), payload.get("bull_case")),
        _section("Bear Case", _bullet_lines([str(point) for point in _coalesce_list(_coalesce_dict(payload.get("bear_case")).get("points"))]), payload.get("bear_case")),
        _section("Key Risks", _bullet_lines([str(item) for item in _coalesce_list(payload.get("key_risks"))]), payload.get("key_risks")),
        _section(
            "Evidence Table",
            _bullet_lines(
                [
                    f"{row.get('category', 'evidence')}: {row.get('claim') or row.get('source') or 'No detail'}"
                    for row in evidence_table
                    if isinstance(row, dict)
                ]
            ),
            evidence_table,
        ),
        _section("Research Conviction", str(payload.get("research_conviction") or "Research conviction unavailable."), payload.get("research_conviction")),
        _section("Filing Context", str(filing_context or "No filing context attached."), filing_context),
        _section("Transcript Context", str(transcript_context or "No transcript context attached."), transcript_context),
        _section("Option Context", str(option_context or "No option context attached."), option_context),
    ]
    summary = payload.get("research_summary") or f"Ticker research memo for {payload.get('ticker', 'unknown')}."
    return _finalize_report(
        report_type="ticker_research",
        fmt=format,
        title=f"Ticker Research Memo: {payload.get('ticker', 'Unknown')}",
        summary=summary,
        sections=sections,
        missing_sections=missing,
        warnings=warnings,
    )


def generate_post_trade_review_report(
    trade_reviews: list[dict] | dict,
    format: str = "markdown",
) -> dict:
    if isinstance(trade_reviews, dict) and "reviews" in trade_reviews:
        reviews = _coalesce_list(trade_reviews.get("reviews"))
        warnings = _coalesce_list(_coalesce_dict(trade_reviews.get("data_quality")).get("warnings"))
    else:
        reviews = _coalesce_list(trade_reviews)
        warnings = []

    missing = ["trade_reviews"] if not reviews else []
    sections = [
        _section(
            "Reviewed Trades",
            "\n\n".join(
                [
                    f"### {review.get('ticker', 'Unknown')}\n"
                    + _bullet_lines(
                        [
                            f"Outcome: {review.get('outcome', 'unknown')}",
                            f"Trade quality: {review.get('trade_quality_label') or _coalesce_dict(review.get('review_json')).get('trade_quality', {}).get('label', 'N/A')}",
                            f"Thesis validity: {review.get('thesis_validity') or _coalesce_dict(review.get('review_json')).get('thesis_analysis', {}).get('thesis_validity', 'N/A')}",
                            f"Review summary: {review.get('review_summary') or _coalesce_dict(review.get('review_json')).get('review_summary', 'N/A')}",
                        ]
                    )
                    for review in reviews
                ]
            ) or "No reviewed trades available.",
            reviews,
        ),
        _section(
            "Lessons",
            _bullet_lines(
                [
                    lesson.get("tag") if isinstance(lesson, dict) else str(lesson)
                    for review in reviews
                    for lesson in _coalesce_list(review.get("lessons_json") or _coalesce_dict(review.get("review_json")).get("lessons"))
                ]
            ),
        ),
        _section(
            "Mistakes",
            _bullet_lines(
                [
                    str(item)
                    for review in reviews
                    for item in _coalesce_list(review.get("mistakes_json") or _coalesce_dict(review.get("review_json")).get("mistakes"))
                ]
            ),
        ),
        _section(
            "Strengths",
            _bullet_lines(
                [
                    str(item)
                    for review in reviews
                    for item in _coalesce_list(review.get("strengths_json") or _coalesce_dict(review.get("review_json")).get("strengths"))
                ]
            ),
        ),
        _section(
            "Rule Adjustments",
            _bullet_lines(
                [
                    str(item)
                    for review in reviews
                    for item in _coalesce_list(review.get("rule_adjustments_json") or _coalesce_dict(review.get("review_json")).get("rule_adjustments"))
                ]
            ),
        ),
        _section(
            "Memory Status",
            _bullet_lines(
                [
                    str(review.get("memory_status_json") or _coalesce_dict(review.get("review_json")).get("memory_status") or "No memory status")
                    for review in reviews
                ]
            ),
        ),
    ]
    summary = f"Post-trade review report covers {len(reviews)} reviewed trades."
    return _finalize_report(
        report_type="post_trade_review",
        fmt=format,
        title="Post-Trade Review Report",
        summary=summary,
        sections=sections,
        missing_sections=missing,
        warnings=warnings,
    )


def generate_full_paper_trading_report(
    db_path: str = "strategy_library.db",
    format: str = "markdown",
) -> dict:
    warnings = [SIMULATION_WARNING]
    missing: list[str] = []

    open_recommendations = get_open_recommendations(db_path=db_path)
    if isinstance(open_recommendations, dict) and open_recommendations.get("ok") is False:
        missing.append("open_recommendations")
        warnings.append(open_recommendations.get("error", "Failed to load open recommendations."))
        open_recommendations = []

    win_loss_record = get_win_loss_record(db_path=db_path)
    if isinstance(win_loss_record, dict) and win_loss_record.get("ok") is False:
        missing.append("win_loss_record")
        warnings.append(win_loss_record.get("error", "Failed to load win/loss record."))
        win_loss_record = {}

    strategy_performance = get_strategy_performance(db_path=db_path)
    if isinstance(strategy_performance, dict) and strategy_performance.get("ok") is False:
        missing.append("strategy_performance")
        warnings.append(strategy_performance.get("error", "Failed to load strategy performance."))
        strategy_performance = {}

    trade_reviews = get_trade_reviews(db_path=db_path)
    if not trade_reviews.get("ok"):
        missing.append("trade_reviews")
        warnings.append(trade_reviews.get("error", "Failed to load trade reviews."))
        trade_reviews = {"ok": False, "reviews": [], "count": 0}

    sections = [
        _section(
            "Open Recommendations",
            _bullet_lines(
                [
                    f"{trade.get('ticker', 'Unknown')}: status={trade.get('status', 'open')}, risk/reward={_fmt_num(trade.get('risk_reward'))}"
                    for trade in _coalesce_list(open_recommendations)
                ]
            ),
            open_recommendations,
        ),
        _section(
            "Performance Summary",
            _bullet_lines(
                [
                    f"Win rate: {_fmt_num(_coalesce_dict(win_loss_record).get('win_rate'))}%",
                    f"Wins: {_coalesce_dict(win_loss_record).get('wins', 0)}",
                    f"Losses: {_coalesce_dict(win_loss_record).get('losses', 0)}",
                    f"Open trades: {_coalesce_dict(win_loss_record).get('open', 0)}",
                ]
            ),
            win_loss_record,
        ),
        _section(
            "Strategy Performance",
            _bullet_lines(
                [
                    f"{item.get('strategy', 'unknown')}: avg_return={_fmt_num(item.get('average_realized_return'))}%"
                    for item in _coalesce_list(_coalesce_dict(strategy_performance).get("by_strategy"))
                ]
            ),
            strategy_performance,
        ),
        _section(
            "Trade Reviews",
            _bullet_lines(
                [
                    f"{review.get('ticker', 'Unknown')}: {review.get('review_summary') or 'Review logged'}"
                    for review in _coalesce_list(trade_reviews.get("reviews"))
                ]
            ),
            trade_reviews,
        ),
    ]
    summary = "Full paper-trading report consolidates open trades, performance, and post-trade reviews from SQLite."
    return _finalize_report(
        report_type="full_paper_trading",
        fmt=format,
        title="Full Paper Trading Report",
        summary=summary,
        sections=sections,
        missing_sections=missing,
        warnings=warnings,
    )
