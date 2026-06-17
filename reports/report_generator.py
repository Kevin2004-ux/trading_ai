from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from journal.trade_journal import get_trade_reviews
from alerts.alert_manager import list_alerts
from analytics.filter_attribution import analyze_filter_attribution
from analytics.performance_attribution import analyze_paper_trade_performance
from analytics.strategy_diagnostics import diagnose_strategy_health
from analytics.trade_error_analysis import analyze_trade_errors
from jobs.job_history import list_job_runs
from tracking.trade_logger import (
    get_candidate_decision_history,
    get_open_recommendations,
    get_strategy_performance,
    get_trade_history,
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


def _scheduled_ops_section(job_history: dict | None, alert_summary: dict | None) -> dict:
    jobs = _coalesce_dict(job_history)
    alerts = _coalesce_dict(alert_summary)
    job_runs = _coalesce_list(jobs.get("job_runs"))
    alert_rows = _coalesce_list(alerts.get("alerts"))
    latest_run = job_runs[0] if job_runs and isinstance(job_runs[0], dict) else {}
    failed_count = len(
        [
            run
            for run in job_runs
            if isinstance(run, dict) and str(run.get("status", "")).lower() == "failed"
        ]
    )
    paper_run = next(
        (
            run
            for run in job_runs
            if isinstance(run, dict)
            and (
                str(run.get("job_type", "")).lower() == "paper_cycle"
                or "paper" in str(run.get("job_name", "")).lower()
            )
        ),
        {},
    )
    body = _bullet_lines(
        [
            f"Latest job: {latest_run.get('job_name', 'N/A')} status={latest_run.get('status', 'N/A')}",
            f"Latest job started: {latest_run.get('started_at', 'N/A')}",
            f"Failed job count in sample: {failed_count}",
            f"Paper-cycle job status: {paper_run.get('status', 'N/A')}",
            f"Recent alert count: {alerts.get('count', len(alert_rows))}",
            f"Severity counts: {alerts.get('severity_counts', {})}",
        ]
    )
    return _section(
        "Scheduled Jobs And Alerts",
        body,
        {
            "job_history": jobs,
            "alert_summary": alerts,
            "failed_job_count": failed_count,
            "paper_cycle_job_status": paper_run.get("status"),
        },
    )


def _performance_diagnostics_from_payload(payload: dict) -> dict:
    return {
        "performance_attribution": _coalesce_dict(payload.get("performance_attribution") or _coalesce_dict(payload.get("summary")).get("performance_attribution")),
        "setup_diagnostics": _coalesce_dict(payload.get("setup_diagnostics") or _coalesce_dict(payload.get("summary")).get("setup_diagnostics")),
        "filter_attribution": _coalesce_dict(payload.get("filter_attribution") or _coalesce_dict(payload.get("summary")).get("filter_attribution")),
        "trade_error_analysis": _coalesce_dict(payload.get("trade_error_analysis") or _coalesce_dict(payload.get("summary")).get("trade_error_analysis")),
    }


def _performance_diagnostics_sections(diagnostics: dict) -> list[dict]:
    performance = _coalesce_dict(diagnostics.get("performance_attribution"))
    setup = _coalesce_dict(diagnostics.get("setup_diagnostics"))
    filters = _coalesce_dict(diagnostics.get("filter_attribution"))
    errors = _coalesce_dict(diagnostics.get("trade_error_analysis"))
    sections: list[dict] = []
    if performance:
        sections.append(
            _section(
                "Performance Attribution",
                _bullet_lines(
                    [
                        f"Closed paper trades: {performance.get('closed_trade_count', 0)}",
                        f"Open paper trades: {performance.get('open_trade_count', 0)}",
                        f"Win rate: {_fmt_num(performance.get('win_rate'))}%",
                        f"Expectancy: {_fmt_num(performance.get('expectancy_r'))}R",
                        f"Profit factor: {_fmt_num(performance.get('profit_factor'))}",
                        f"Max drawdown: {_fmt_num(performance.get('max_drawdown_r'))}R",
                        f"Best trade: {_coalesce_dict(performance.get('best_trade')).get('ticker', 'N/A')}",
                        f"Worst trade: {_coalesce_dict(performance.get('worst_trade')).get('ticker', 'N/A')}",
                        *[f"Warning: {warning}" for warning in _coalesce_list(performance.get("warnings"))[:5]],
                    ]
                ),
                performance,
            )
        )
    if setup:
        setup_rows = _coalesce_list(setup.get("setups"))
        sections.append(
            _section(
                "Setup Diagnostics",
                _bullet_lines(
                    [
                        f"Overall status: {setup.get('overall_status', 'N/A')}",
                        *[
                            f"{row.get('setup_type', 'unknown')}: status={row.get('status')}, expectancy={_fmt_num(row.get('expectancy_r'))}R, win_rate={_fmt_num(row.get('win_rate'))}%"
                            for row in setup_rows[:10]
                            if isinstance(row, dict)
                        ],
                        *[f"Recommendation: {item}" for item in _coalesce_list(setup.get("recommendations"))[:5]],
                    ]
                ),
                setup,
            )
        )
    if filters:
        filter_rows = _coalesce_list(filters.get("filters"))
        sections.append(
            _section(
                "Filter Attribution",
                _bullet_lines(
                    [
                        *[
                            f"{row.get('filter_name', 'unknown')}: status={row.get('diagnostic_status')}, applied={row.get('applied_count', 0)}, blocked={row.get('blocked_count', 0)}, downgraded={row.get('downgraded_count', 0)}"
                            for row in filter_rows[:12]
                            if isinstance(row, dict)
                        ],
                        *[f"Warning: {warning}" for warning in _coalesce_list(filters.get("warnings"))[:5]],
                    ]
                ),
                filters,
            )
        )
    if errors:
        top_modes = _coalesce_list(errors.get("top_failure_modes"))
        sections.append(
            _section(
                "Trade Error Analysis",
                _bullet_lines(
                    [
                        *[
                            f"{row.get('category', 'unknown')}: {row.get('count', 0)}"
                            for row in top_modes[:8]
                            if isinstance(row, dict)
                        ],
                        *[f"Recommendation: {item}" for item in _coalesce_list(errors.get("recommendations"))[:5]],
                        *[f"Warning: {warning}" for warning in _coalesce_list(errors.get("warnings"))[:5]],
                    ]
                ),
                errors,
            )
        )
    return sections


def _stress_test_section(stress_summary: dict | None) -> dict:
    stress = _coalesce_dict(stress_summary)
    results = _coalesce_list(stress.get("results"))
    portfolio = _coalesce_dict(stress.get("portfolio_stress"))
    body = _bullet_lines(
        [
            f"Scenarios run: {stress.get('scenario_count', len(results))}",
            f"Passed expected behavior: {stress.get('passed_count', 0)}",
            f"Failed expected behavior: {stress.get('failed_count', 0)}",
            f"Blocked-new-trades scenarios: {stress.get('blocked_new_trades_count', 0)}",
            f"Risk-reduced scenarios: {stress.get('risk_reduced_count', 0)}",
            f"Estimated portfolio stress loss: {_fmt_num(portfolio.get('estimated_total_loss_r'))}R",
            *[
                f"{item.get('scenario_name', 'unknown')}: passed={item.get('passed_expected_behavior')}, severity={item.get('severity')}"
                for item in results[:10]
                if isinstance(item, dict)
            ],
            *[
                f"Critical finding: {item.get('scenario_name', 'unknown')} - {item.get('message', '')}"
                for item in _coalesce_list(stress.get("critical_findings"))[:6]
                if isinstance(item, dict)
            ],
            *[f"Warning: {warning}" for warning in _coalesce_list(stress.get("warnings"))[:6]],
        ]
    ) if stress else "No stress-test summary attached."
    return _section("Stress Test Summary", body, stress)


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
    option_trade_risk = _coalesce_dict(trade.get("preferred_option_trade_risk"))
    selected_strategy = _coalesce_dict(trade.get("selected_option_strategy"))
    paper_fill = _coalesce_dict(trade.get("paper_fill"))
    filing_sentiment = _coalesce_dict(trade.get("filing_sentiment"))
    if not filing_sentiment:
        filing_sentiment = _coalesce_dict(_coalesce_dict(trade.get("source_candidate")).get("filing_sentiment"))
    short_interest = _coalesce_dict(trade.get("short_interest"))
    borrow_pressure = _coalesce_dict(trade.get("borrow_pressure"))
    news_sentiment = _coalesce_dict(trade.get("news_sentiment"))
    source_candidate = _coalesce_dict(trade.get("source_candidate"))
    if not short_interest:
        short_interest = _coalesce_dict(source_candidate.get("short_interest"))
    if not borrow_pressure:
        borrow_pressure = _coalesce_dict(source_candidate.get("borrow_pressure"))
    if not news_sentiment:
        news_sentiment = _coalesce_dict(source_candidate.get("news_sentiment"))
    if not paper_fill:
        source_candidate = _coalesce_dict(trade.get("source_candidate"))
        paper_fill = _coalesce_dict(source_candidate.get("paper_fill"))
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
    if filing_sentiment:
        lines.extend(
            [
                f"Filing sentiment: {filing_sentiment.get('sentiment_label', 'N/A')}",
                f"Filing risk level: {filing_sentiment.get('filing_risk_level', 'N/A')}",
                f"Filing trade impact: {filing_sentiment.get('trade_impact', 'N/A')}",
                f"Filing risk multiplier: {_fmt_num(filing_sentiment.get('risk_multiplier'))}",
            ]
        )
    if short_interest:
        lines.extend(
            [
                f"Short interest level: {short_interest.get('short_interest_level', 'N/A')}",
                f"Days to cover: {_fmt_num(short_interest.get('days_to_cover'))}",
                f"Squeeze risk: {short_interest.get('squeeze_risk', 'N/A')}",
            ]
        )
    if borrow_pressure:
        lines.append(f"Borrow pressure: {borrow_pressure.get('borrow_pressure', 'N/A')}")
    if news_sentiment:
        lines.extend(
            [
                f"Headline sentiment: {news_sentiment.get('sentiment_label', 'N/A')}",
                f"Headline risk: {news_sentiment.get('headline_risk_level', 'N/A')}",
                f"Headline risk flags: {', '.join(str(flag) for flag in _coalesce_list(news_sentiment.get('risk_flags'))) or 'N/A'}",
            ]
        )
    if paper_fill:
        lines.extend(
            [
                f"Intended entry: {_fmt_price(paper_fill.get('intended_entry_price'))}",
                f"Estimated paper fill: {_fmt_price(paper_fill.get('estimated_fill_price'))}",
                f"Fill quality: {paper_fill.get('fill_quality', 'N/A')}",
                f"Fill warning: {paper_fill.get('paper_fill_warning') or 'Simulated fill; no live order was placed.'}",
            ]
        )
    if trade.get("preferred_option_contract"):
        lines.append(f"Preferred option: {trade.get('preferred_option_contract')}")
    elif isinstance(trade.get("option_alternatives"), list) and trade["option_alternatives"]:
        lines.append(f"Option alternative: {trade['option_alternatives'][0].get('option_contract', 'N/A')}")
    if option_context:
        lines.append(f"Option context: {option_context.get('mispricing_label') or option_context}")
    if option_trade_risk:
        iv_context = _coalesce_dict(option_trade_risk.get("iv_context"))
        greeks = _coalesce_dict(option_trade_risk.get("greeks"))
        lines.extend(
            [
                f"Option risk status: {option_trade_risk.get('status', 'N/A')}",
                f"IV rank/percentile: {_fmt_num(iv_context.get('iv_rank'))}/{_fmt_num(iv_context.get('iv_percentile'))}",
                f"IV context: {iv_context.get('iv_context', 'N/A')}",
                f"Greeks quality: {greeks.get('greeks_quality', 'N/A')}",
                f"DTE risk: {option_trade_risk.get('days_to_expiration', 'N/A')} DTE",
                f"Option fill quality: {option_trade_risk.get('fill_quality', 'N/A')}",
            ]
        )
    if selected_strategy:
        lines.extend(
            [
                f"Selected option strategy: {selected_strategy.get('strategy_type', 'N/A')}",
                f"Strategy status: {selected_strategy.get('status', 'N/A')}",
                f"Strategy debit/credit: {_fmt_num(selected_strategy.get('net_debit'))}/{_fmt_num(selected_strategy.get('net_credit'))}",
                f"Strategy max loss/profit: {_fmt_num(selected_strategy.get('max_loss'))}/{_fmt_num(selected_strategy.get('max_profit'))}",
                f"Strategy breakeven: {_fmt_price(selected_strategy.get('breakeven'))}",
            ]
        )
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
    summary_payload = _coalesce_dict(payload.get("summary"))
    concentration_summary = _coalesce_dict(payload.get("concentration_summary") or summary_payload.get("concentration_summary") or decision_result.get("concentration_summary") or selection_result.get("concentration_summary"))
    technical_confirmation_summary = _coalesce_dict(payload.get("technical_confirmation_summary") or summary_payload.get("technical_confirmation_summary") or decision_result.get("technical_confirmation_summary") or selection_result.get("technical_confirmation_summary"))
    option_research = _coalesce_dict(payload.get("option_research") or selection_result.get("option_research"))
    option_risk_summary = _coalesce_dict(payload.get("option_risk_summary") or summary_payload.get("option_risk_summary") or selection_result.get("option_risk_summary") or option_research.get("option_risk_summary"))
    option_strategy_summary = _coalesce_dict(payload.get("option_strategy_summary") or summary_payload.get("option_strategy_summary") or selection_result.get("option_strategy_summary") or _coalesce_dict(option_research.get("summary")).get("option_strategy_summary"))
    macro_risk = _coalesce_dict(payload.get("macro_risk") or summary_payload.get("macro_risk") or decision_result.get("macro_risk"))
    circuit_breaker = _coalesce_dict(summary_payload.get("circuit_breaker") or _coalesce_dict(decision_result).get("circuit_breaker"))
    setup_decay = _coalesce_dict(summary_payload.get("setup_decay") or _coalesce_dict(decision_result).get("setup_decay"))
    scan_execution = _coalesce_dict(payload.get("scan_execution_summary") or summary_payload.get("scan_execution_summary") or _coalesce_dict(payload.get("scan_result")).get("scan_execution_summary"))
    pipeline_run = _coalesce_dict(payload.get("pipeline_run"))
    checkpoint_summary = _coalesce_dict(payload.get("checkpoint_summary"))
    audit_status = _coalesce_dict(payload.get("audit_status"))
    schema_version = _coalesce_dict(payload.get("schema_version"))
    startup_readiness = _coalesce_dict(payload.get("startup_readiness") or summary_payload.get("startup_readiness"))
    job_history = _coalesce_dict(payload.get("job_history") or summary_payload.get("job_history"))
    alert_summary = _coalesce_dict(payload.get("alert_summary") or summary_payload.get("alert_summary"))
    gemini_validation = _coalesce_dict(payload.get("gemini_validation") or payload.get("validation") or summary_payload.get("gemini_validation"))
    memory_summary = _coalesce_dict(payload.get("memory_summary") or summary_payload.get("memory_summary") or _coalesce_dict(payload.get("decision_result")).get("memory_summary"))
    stress_test_summary = _coalesce_dict(payload.get("stress_test_summary") or summary_payload.get("stress_test_summary"))
    performance_diagnostics = _performance_diagnostics_from_payload(payload)
    selected_trades = _coalesce_list(decision_result.get("final_recommendations"))
    watchlist = _coalesce_list(selection_result.get("watchlist_alternatives"))
    risk_rejected = _coalesce_list(decision_result.get("risk_rejected"))
    rejected = _coalesce_list(selection_result.get("rejected_candidates")) + _coalesce_list(decision_result.get("not_selected"))
    warnings = [SIMULATION_WARNING]
    missing: list[str] = []
    scan_quality = _coalesce_dict(_coalesce_dict(payload.get("scan_result")).get("data_quality_summary"))
    summary_quality = _coalesce_dict(_coalesce_dict(payload.get("summary")).get("data_quality"))
    for quality_payload in (scan_quality, summary_quality):
        quality_warnings = _coalesce_list(quality_payload.get("warnings"))
        quality_errors = _coalesce_list(quality_payload.get("errors"))
        if quality_payload:
            warnings.append(f"Data quality summary: {quality_payload.get('worst_quality_label', 'unknown')}.")
        warnings.extend(str(item) for item in quality_warnings[:5])
        warnings.extend(str(item) for item in quality_errors[:5])
    warnings.extend(str(item) for item in _coalesce_list(scan_execution.get("warnings"))[:5])

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
    option_risk_evaluations = _coalesce_list(option_risk_summary.get("evaluations"))
    option_risk_body = _bullet_lines(
        [
            f"Evaluated option contracts: {option_risk_summary.get('evaluated_count', 0)}",
            f"Paper-eligible contracts: {option_risk_summary.get('approved_count', 0)}",
            f"Research-only contracts: {option_risk_summary.get('research_only_count', 0)}",
            f"Blocked contracts: {option_risk_summary.get('blocked_count', 0)}",
            *[
                (
                    f"{item.get('option_contract', 'Unknown')}: status={_coalesce_dict(item.get('option_trade_risk')).get('status')}, "
                    f"IV={_coalesce_dict(item.get('iv_context')).get('iv_context', 'N/A')} "
                    f"rank={_fmt_num(_coalesce_dict(item.get('iv_context')).get('iv_rank'))}, "
                    f"greeks={_coalesce_dict(item.get('greeks_monitoring')).get('greeks_quality', 'N/A')}, "
                    f"DTE={_coalesce_dict(item.get('option_trade_risk')).get('days_to_expiration', 'N/A')}, "
                    f"spread/fill={_coalesce_dict(item.get('option_trade_risk')).get('spread_quality', 'N/A')}/{_coalesce_dict(item.get('option_trade_risk')).get('fill_quality', 'N/A')}"
                )
                for item in option_risk_evaluations[:10]
                if isinstance(item, dict)
            ],
        ]
    ) if option_risk_summary else "No IV/Greeks option risk context attached."
    strategy_candidates = _coalesce_list(option_research.get("option_strategy_candidates"))
    if not strategy_candidates:
        strategy_candidates = _coalesce_list(option_research.get("selected_option_strategies"))
    strategy_body = _bullet_lines(
        [
            f"Strategy candidates: {option_strategy_summary.get('strategy_count', 0)}",
            f"Paper-eligible strategies: {option_strategy_summary.get('paper_eligible_count', 0)}",
            f"Research-only strategies: {option_strategy_summary.get('research_only_count', 0)}",
            f"Blocked strategies: {option_strategy_summary.get('blocked_count', 0)}",
            *[
                (
                    f"{item.get('strategy_type', 'Unknown')}: status={item.get('status', 'N/A')}, "
                    f"debit={_fmt_num(item.get('net_debit'))}, credit={_fmt_num(item.get('net_credit'))}, "
                    f"max_loss={_fmt_num(item.get('max_loss'))}, max_profit={_fmt_num(item.get('max_profit'))}, "
                    f"breakeven={_fmt_price(item.get('breakeven'))}"
                )
                for item in strategy_candidates[:10]
                if isinstance(item, dict)
            ],
        ]
    ) if option_strategy_summary else "No option strategy comparison context attached."
    macro_body = _bullet_lines(
        [
            f"Risk level: {macro_risk.get('macro_risk_level', 'N/A')}",
            f"Risk multiplier: {_fmt_num(macro_risk.get('risk_multiplier'))}",
            f"New trades allowed: {macro_risk.get('new_trades_allowed', 'N/A')}",
            f"Active events: {len(_coalesce_list(macro_risk.get('active_events')))}",
            f"Upcoming events: {len(_coalesce_list(macro_risk.get('upcoming_events')))}",
            *[f"Warning: {warning}" for warning in _coalesce_list(macro_risk.get("warnings"))],
            *[f"Reason: {reason}" for reason in _coalesce_list(macro_risk.get("reasons"))],
        ]
    ) if macro_risk else "No macro risk context attached."
    regime_body = _bullet_lines(
        [
            f"Regime: {market_regime.get('regime', 'N/A')}",
            f"Risk level: {market_regime.get('risk_level', 'N/A')}",
            f"Confidence: {_fmt_num(market_regime.get('confidence'))}",
            f"Stock risk multiplier: {_fmt_num(market_regime.get('stock_risk_multiplier'))}",
            f"Option risk multiplier: {_fmt_num(market_regime.get('option_risk_multiplier'))}",
            f"Allowed setups: {', '.join(str(item) for item in _coalesce_list(market_regime.get('allowed_setups'))) or 'N/A'}",
            f"Blocked setups: {', '.join(str(item) for item in _coalesce_list(market_regime.get('blocked_setups'))) or 'N/A'}",
            *[f"Warning: {warning}" for warning in _coalesce_list(market_regime.get("warnings"))],
        ]
    ) if market_regime else "Market regime summary unavailable."
    concentration_snapshot = _coalesce_dict(concentration_summary.get("snapshot"))
    latest_snapshot = _coalesce_dict(concentration_snapshot.get("latest_snapshot"))
    snapshot_payload = _coalesce_dict(latest_snapshot.get("snapshot"))
    concentration_evaluations = _coalesce_list(concentration_summary.get("evaluations"))
    concentration_body = _bullet_lines(
        [
            f"Snapshot source: {concentration_snapshot.get('source', 'N/A')}",
            f"Latest snapshot age hours: {_fmt_num(snapshot_payload.get('age_hours'))}",
            f"Evaluated candidates: {concentration_summary.get('evaluated_count', 0)}",
            f"Blocked candidates: {concentration_summary.get('blocked_count', 0)}",
            f"Reduced-risk candidates: {concentration_summary.get('reduced_count', 0)}",
            *[
                f"{item.get('ticker', 'Unknown')}: risk_level={_coalesce_dict(item.get('concentration_risk')).get('risk_level')}, multiplier={_fmt_num(_coalesce_dict(item.get('concentration_risk')).get('risk_multiplier'))}"
                for item in concentration_evaluations
                if isinstance(item, dict)
            ],
            *[f"Warning: {warning}" for warning in _coalesce_list(concentration_snapshot.get("warnings"))[:5]],
        ]
    ) if concentration_summary else "No concentration risk context attached."
    technical_evaluations = _coalesce_list(technical_confirmation_summary.get("evaluations"))
    technical_body = _bullet_lines(
        [
            f"Evaluated candidates: {technical_confirmation_summary.get('evaluated_count', 0)}",
            f"Rejected by technical confirmation: {technical_confirmation_summary.get('rejected_count', 0)}",
            f"Warning/downgraded candidates: {technical_confirmation_summary.get('warning_count', 0)}",
            *[
                (
                    f"{item.get('ticker', 'Unknown')}: status={_coalesce_dict(item.get('technical_confirmation_summary')).get('status')}, "
                    f"score_adjustment={_fmt_num(_coalesce_dict(item.get('technical_confirmation_summary')).get('score_adjustment'))}, "
                    f"risk_multiplier={_fmt_num(_coalesce_dict(item.get('technical_confirmation_summary')).get('risk_multiplier'))}, "
                    f"POC={_fmt_price(_coalesce_dict(item.get('volume_profile_confirmation')).get('point_of_control'))}, "
                    f"value_area={_fmt_price(_coalesce_dict(item.get('volume_profile_confirmation')).get('value_area_low'))}-{_fmt_price(_coalesce_dict(item.get('volume_profile_confirmation')).get('value_area_high'))}, "
                    f"daily={_coalesce_dict(item.get('timeframe_confirmation')).get('daily_trend', 'N/A')}, "
                    f"weekly={_coalesce_dict(item.get('timeframe_confirmation')).get('weekly_trend', 'N/A')}"
                )
                for item in technical_evaluations
                if isinstance(item, dict)
            ],
        ]
    ) if technical_confirmation_summary else "No technical confirmation context attached."
    filing_summary = _coalesce_dict(payload.get("filing_sentiment_summary") or summary_payload.get("filing_sentiment_summary") or decision_result.get("filing_sentiment_summary") or selection_result.get("filing_sentiment_summary"))
    filing_evaluations = _coalesce_list(filing_summary.get("evaluations"))
    if not filing_evaluations:
        for collection_name, collection in (
            ("selected", selected_trades),
            ("watchlist", watchlist),
            ("rejected", rejected + risk_rejected),
        ):
            for item in collection:
                candidate = _coalesce_dict(_coalesce_dict(item).get("candidate")) or _coalesce_dict(item)
                sentiment = _coalesce_dict(candidate.get("filing_sentiment") or _coalesce_dict(candidate.get("source_candidate")).get("filing_sentiment"))
                analysis = _coalesce_dict(candidate.get("filing_analysis") or _coalesce_dict(candidate.get("source_candidate")).get("filing_analysis"))
                earnings = _coalesce_dict(candidate.get("earnings_8k_analysis") or _coalesce_dict(candidate.get("source_candidate")).get("earnings_8k_analysis"))
                if sentiment or analysis or earnings:
                    filing_evaluations.append(
                        {
                            "ticker": candidate.get("ticker"),
                            "bucket": collection_name,
                            "filing_sentiment": sentiment,
                            "filing_analysis": analysis,
                            "earnings_8k_analysis": earnings,
                        }
                    )
    filing_body = _bullet_lines(
        [
            f"Evaluated candidates: {filing_summary.get('evaluated_count', len(filing_evaluations))}",
            f"Critical/blocking candidates: {filing_summary.get('blocking_count', 0)}",
            f"High-risk candidates: {filing_summary.get('high_risk_count', 0)}",
            *[
                (
                    f"{item.get('ticker', 'Unknown')}: bucket={item.get('bucket', 'N/A')}, "
                    f"sentiment={_coalesce_dict(item.get('filing_sentiment')).get('sentiment_label', 'N/A')}, "
                    f"risk={_coalesce_dict(item.get('filing_sentiment')).get('filing_risk_level', _coalesce_dict(item.get('filing_analysis')).get('filing_risk_level', 'N/A'))}, "
                    f"impact={_coalesce_dict(item.get('filing_sentiment')).get('trade_impact', 'N/A')}, "
                    f"events={', '.join(str(event) for event in _coalesce_list(_coalesce_dict(item.get('filing_analysis')).get('material_events'))[:3]) or 'N/A'}, "
                    f"earnings_8k={_coalesce_dict(item.get('earnings_8k_analysis')).get('sentiment_label', 'N/A')}"
                )
                for item in filing_evaluations[:10]
                if isinstance(item, dict)
            ],
        ]
    ) if (filing_summary or filing_evaluations) else "No SEC filing sentiment context attached."
    research_risk_summary = _coalesce_dict(payload.get("research_risk_summary") or summary_payload.get("research_risk_summary") or decision_result.get("research_risk_summary") or selection_result.get("research_risk_summary"))
    research_evaluations = _coalesce_list(research_risk_summary.get("evaluations"))
    if not research_evaluations:
        for collection_name, collection in (
            ("selected", selected_trades),
            ("watchlist", watchlist),
            ("rejected", rejected + risk_rejected),
        ):
            for item in collection:
                candidate = _coalesce_dict(_coalesce_dict(item).get("candidate")) or _coalesce_dict(item)
                source = _coalesce_dict(candidate.get("source_candidate"))
                short_context = _coalesce_dict(candidate.get("short_interest") or source.get("short_interest"))
                borrow_context = _coalesce_dict(candidate.get("borrow_pressure") or source.get("borrow_pressure"))
                news_context = _coalesce_dict(candidate.get("news_sentiment") or source.get("news_sentiment"))
                if short_context or borrow_context or news_context:
                    research_evaluations.append(
                        {
                            "ticker": candidate.get("ticker"),
                            "bucket": collection_name,
                            "short_interest": short_context,
                            "borrow_pressure": borrow_context,
                            "news_sentiment": news_context,
                        }
                    )
    research_risk_body = _bullet_lines(
        [
            f"Evaluated candidates: {research_risk_summary.get('evaluated_count', len(research_evaluations))}",
            f"Blocking research risks: {research_risk_summary.get('blocking_count', 0)}",
            f"Reduced-risk candidates: {research_risk_summary.get('reduced_count', 0)}",
            *[
                (
                    f"{item.get('ticker', 'Unknown')}: bucket={item.get('bucket', 'N/A')}, "
                    f"short={_coalesce_dict(item.get('short_interest')).get('short_interest_level', 'N/A')}, "
                    f"days_to_cover={_fmt_num(_coalesce_dict(item.get('short_interest')).get('days_to_cover'))}, "
                    f"squeeze={_coalesce_dict(item.get('short_interest')).get('squeeze_risk', 'N/A')}, "
                    f"borrow={_coalesce_dict(item.get('borrow_pressure')).get('borrow_pressure', 'N/A')}, "
                    f"headline={_coalesce_dict(item.get('news_sentiment')).get('sentiment_label', 'N/A')}, "
                    f"headline_risk={_coalesce_dict(item.get('news_sentiment')).get('headline_risk_level', 'N/A')}, "
                    f"flags={', '.join(str(flag) for flag in _coalesce_list(_coalesce_dict(item.get('news_sentiment')).get('risk_flags'))[:3]) or 'N/A'}"
                )
                for item in research_evaluations[:10]
                if isinstance(item, dict)
            ],
        ]
    ) if (research_risk_summary or research_evaluations) else "No short-interest, borrow, or news risk context attached."
    memory_rows = []
    for trade in selected_trades:
        if not isinstance(trade, dict):
            continue
        context = _coalesce_dict(trade.get("memory_context"))
        quality = _coalesce_dict(context.get("retrieval_quality") or trade.get("retrieval_quality"))
        impact = _coalesce_dict(context.get("memory_impact"))
        feedback = _coalesce_dict(context.get("human_feedback") or trade.get("human_feedback"))
        if context or quality or feedback:
            memory_rows.append(
                (
                    f"{trade.get('ticker', 'Unknown')}: quality={quality.get('quality_status', 'N/A')}, "
                    f"top_similarity={_fmt_num(quality.get('top_score'))}, "
                    f"decision_support={quality.get('usable_for_decision_support', False)}, "
                    f"explanation={quality.get('usable_for_explanation', False)}, "
                    f"impact={impact.get('trade_impact', 'N/A')}, "
                    f"score_adjustment={_fmt_num(impact.get('score_adjustment'))}, "
                    f"risk_multiplier={_fmt_num(impact.get('risk_multiplier'))}, "
                    f"feedback={feedback.get('feedback_status', 'N/A')}"
                )
            )
    memory_body = _bullet_lines(
        [
            f"Memory enabled: {memory_summary.get('enabled', False)}",
            f"Evaluated candidates: {memory_summary.get('evaluated_count', len(memory_rows))}",
            f"Used for decision support: {memory_summary.get('decision_support_count', 0)}",
            f"Explanation-only: {memory_summary.get('explanation_only_count', 0)}",
            f"Ignored/failed quality: {memory_summary.get('ignored_count', 0)}",
            *memory_rows,
            *[f"Warning: {warning}" for warning in _coalesce_list(memory_summary.get("warnings"))[:8]],
        ]
    ) if (memory_summary or memory_rows) else "Memory is disabled or no retrieval quality context was attached."
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
    circuit_body = _bullet_lines(
        [
            f"Status: {circuit_breaker.get('circuit_status', 'N/A')}",
            f"Loss streak: {circuit_breaker.get('rolling_loss_streak', 'N/A')}",
            f"Recent win rate: {_fmt_num(circuit_breaker.get('recent_win_rate'))}%",
            f"Recent expectancy: {_fmt_num(circuit_breaker.get('recent_expectancy_r'))}R",
            f"Risk multiplier: {_fmt_num(circuit_breaker.get('max_allowed_risk_multiplier'))}",
            *[f"Reason: {reason}" for reason in _coalesce_list(circuit_breaker.get("reasons"))],
        ]
    ) if circuit_breaker else "No circuit breaker context attached."
    setup_decay_table = _coalesce_dict(setup_decay.get("setups"))
    setup_decay_body = _bullet_lines(
        [
            f"{name}: status={item.get('status')}, sample={item.get('sample_size')}, expectancy={_fmt_num(item.get('recent_expectancy_r'))}R"
            for name, item in setup_decay_table.items()
            if isinstance(item, dict)
        ]
    ) if setup_decay_table else "No setup decay context attached."
    scan_execution_body = _bullet_lines(
        [
            f"Duration seconds: {_fmt_num(scan_execution.get('duration_seconds'))}",
            f"Total tickers: {scan_execution.get('total_tickers', 'N/A')}",
            f"Completed tickers: {scan_execution.get('completed_tickers', 'N/A')}",
            f"Failed tickers: {len(_coalesce_list(scan_execution.get('failed_tickers')))}",
            f"Timed-out tickers: {len(_coalesce_list(scan_execution.get('timed_out_tickers')))}",
            f"Partial results used: {scan_execution.get('partial_results_used', False)}",
            *[f"Warning: {warning}" for warning in _coalesce_list(scan_execution.get("warnings"))],
        ]
    ) if scan_execution else "No scan execution summary attached."
    pipeline_body = _bullet_lines(
        [
            f"Run id: {payload.get('run_id') or pipeline_run.get('run_id') or summary_payload.get('pipeline_run_id') or 'N/A'}",
            f"Pipeline status: {pipeline_run.get('status', 'N/A')}",
            f"Checkpoint count: {checkpoint_summary.get('count', summary_payload.get('checkpoint_count', 'N/A'))}",
            f"Audit chain ok: {audit_status.get('ok', summary_payload.get('audit_chain_ok', 'N/A'))}",
            f"Schema version: {schema_version.get('current_version', 'N/A')}",
        ]
    ) if (pipeline_run or checkpoint_summary or audit_status or payload.get("run_id") or summary_payload.get("pipeline_run_id")) else "No pipeline or audit summary attached."
    startup_body = _bullet_lines(
        [
            f"Readiness: {startup_readiness.get('readiness', 'N/A')}",
            f"Safe to run paper cycle: {startup_readiness.get('safe_to_run_paper_cycle', 'N/A')}",
            f"Safe to run options: {startup_readiness.get('safe_to_run_options', 'N/A')}",
            *[f"Warning: {warning}" for warning in _coalesce_list(startup_readiness.get("warnings"))[:5]],
            *[f"Blocking/error: {error}" for error in _coalesce_list(startup_readiness.get("errors"))[:5]],
        ]
    ) if startup_readiness else "No startup readiness summary attached."
    gemini_issues = _coalesce_list(gemini_validation.get("issues"))
    gemini_body = _bullet_lines(
        [
            f"Validation status: {gemini_validation.get('validation_status', 'N/A')}",
            f"Safe to show user: {gemini_validation.get('safe_to_show_user', 'N/A')}",
            f"Safe to log: {gemini_validation.get('safe_to_log', 'N/A')}",
            f"Deterministic fallback used: {gemini_validation.get('deterministic_fallback_used', False)}",
            *[
                f"{issue.get('severity', 'issue')} {issue.get('code', 'unknown')}: {issue.get('message', '')}"
                for issue in gemini_issues[:8]
                if isinstance(issue, dict)
            ],
        ]
    ) if gemini_validation else "No Gemini narrative validation was run for this report. Deterministic report content remains the source of truth."
    final_warning_body = _bullet_lines(
        [
            SIMULATION_WARNING,
            "Reports summarize deterministic system output and do not create new trades by themselves.",
            *(_coalesce_list(payload.get("errors"))[:5]),
        ]
    )

    sections = [
        _section("Macro Risk", macro_body, macro_risk),
        _section("Market Regime", regime_body, market_regime),
        _section("Correlation And Concentration", concentration_body, concentration_summary),
        _section("Technical Confirmation", technical_body, technical_confirmation_summary),
        _section("SEC Filing Sentiment", filing_body, filing_summary or filing_evaluations),
        _section("Short Interest And News Risk", research_risk_body, research_risk_summary or research_evaluations),
        _section("Memory And Human Feedback", memory_body, {"memory_summary": memory_summary, "selected_trades": selected_trades}),
        _section("Selected Trades", selected_body, selected_trades),
        _section("Watchlist Alternatives", watchlist_body, watchlist),
        _section("Rejected Or Risk-Rejected", rejected_body, {"risk_rejected": risk_rejected, "rejected": rejected}),
        _section("Option Alternatives", option_body, selected_trades),
        _section("Options IV And Greeks Risk", option_risk_body, option_risk_summary),
        _section("Option Strategy Comparison", strategy_body, option_strategy_summary),
        _section("Portfolio Risk", risk_summary, portfolio_risk),
        _section("Position Sizing", sizing_body, selected_trades),
        _section("Scan Execution", scan_execution_body, scan_execution),
        _section("Startup Readiness", startup_body, startup_readiness),
        _section("Gemini Validation", gemini_body, gemini_validation),
        _section("Pipeline And Audit", pipeline_body, {"pipeline_run": pipeline_run, "checkpoint_summary": checkpoint_summary, "audit_status": audit_status}),
        _stress_test_section(stress_test_summary),
        *_performance_diagnostics_sections(performance_diagnostics),
        _section("Circuit Breaker", circuit_body, circuit_breaker),
        _section("Setup Decay", setup_decay_body, setup_decay),
        _section("Research And Memory Notes", notes_body, selected_trades),
        _scheduled_ops_section(job_history, alert_summary),
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

    job_history = list_job_runs(db_path=db_path, limit=20)
    if not job_history.get("ok"):
        missing.append("job_history")
        warnings.append(job_history.get("error", "Failed to load scheduled job history."))
        job_history = {}

    alert_summary = list_alerts(db_path=db_path, limit=20)
    if not alert_summary.get("ok"):
        missing.append("alert_summary")
        warnings.append(alert_summary.get("error", "Failed to load alert summary."))
        alert_summary = {}

    trade_history = get_trade_history(db_path=db_path)
    if isinstance(trade_history, dict) and trade_history.get("ok") is False:
        missing.append("trade_history")
        warnings.append(trade_history.get("error", "Failed to load trade history."))
        trade_history = []
    candidate_history = get_candidate_decision_history(db_path=db_path)
    if isinstance(candidate_history, dict) and candidate_history.get("ok") is False:
        missing.append("candidate_history")
        warnings.append(candidate_history.get("error", "Failed to load candidate history."))
        candidate_history = []
    performance_diagnostics = {
        "performance_attribution": analyze_paper_trade_performance(trade_history if isinstance(trade_history, list) else []),
        "setup_diagnostics": diagnose_strategy_health(trade_history if isinstance(trade_history, list) else []),
        "filter_attribution": analyze_filter_attribution(candidate_history if isinstance(candidate_history, list) else [], trades=trade_history if isinstance(trade_history, list) else []),
        "trade_error_analysis": analyze_trade_errors(trade_history if isinstance(trade_history, list) else []),
    }

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
        *_performance_diagnostics_sections(performance_diagnostics),
        _scheduled_ops_section(job_history, alert_summary),
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


def generate_performance_diagnostics_report(
    db_path: str = "strategy_library.db",
    format: str = "markdown",
) -> dict:
    warnings = [SIMULATION_WARNING]
    missing: list[str] = []
    trade_history = get_trade_history(db_path=db_path)
    if isinstance(trade_history, dict) and trade_history.get("ok") is False:
        missing.append("trade_history")
        warnings.append(trade_history.get("error", "Failed to load trade history."))
        trade_history = []
    candidate_history = get_candidate_decision_history(db_path=db_path)
    if isinstance(candidate_history, dict) and candidate_history.get("ok") is False:
        missing.append("candidate_history")
        warnings.append(candidate_history.get("error", "Failed to load candidate history."))
        candidate_history = []
    diagnostics = {
        "performance_attribution": analyze_paper_trade_performance(trade_history if isinstance(trade_history, list) else []),
        "setup_diagnostics": diagnose_strategy_health(trade_history if isinstance(trade_history, list) else []),
        "filter_attribution": analyze_filter_attribution(candidate_history if isinstance(candidate_history, list) else [], trades=trade_history if isinstance(trade_history, list) else []),
        "trade_error_analysis": analyze_trade_errors(trade_history if isinstance(trade_history, list) else []),
    }
    sections = _performance_diagnostics_sections(diagnostics)
    if not sections:
        missing.append("performance_diagnostics")
    summary = "Performance diagnostics analyze simulated paper trades only; they do not represent live brokerage performance."
    return _finalize_report(
        report_type="performance_diagnostics",
        fmt=format,
        title="Paper Performance Diagnostics",
        summary=summary,
        sections=sections,
        missing_sections=missing,
        warnings=warnings,
    )
