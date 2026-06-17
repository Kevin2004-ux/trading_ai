from __future__ import annotations

from typing import Any

from .grounding import extract_grounding_facts


def _fmt_price(value: Any) -> str:
    try:
        if value is None:
            return "N/A"
        return f"${float(value):.2f}"
    except (TypeError, ValueError):
        return "N/A"


def _fmt_num(value: Any) -> str:
    try:
        if value is None:
            return "N/A"
        return f"{float(value):.2f}"
    except (TypeError, ValueError):
        return "N/A"


def _as_list(value: Any) -> list:
    return value if isinstance(value, list) else []


def format_validated_trade_response(
    validated_output: dict,
    fallback_result: dict | None = None,
    config: dict | None = None,
) -> str:
    if not isinstance(validated_output, dict) or not validated_output.get("safe_to_show_user"):
        return format_deterministic_fallback_response(fallback_result or {}, config=config)
    payload = validated_output.get("normalized_output") or {}
    if not isinstance(payload, dict):
        return format_deterministic_fallback_response(fallback_result or {}, config=config)

    lines = [str(payload.get("plain_english_summary") or "Trading-brain summary:"), "", "Paper trading only. No real brokerage order was placed."]
    final_trades = _as_list(payload.get("final_paper_trades"))
    if final_trades:
        lines.extend(["", "Final Paper Trades:"])
        for trade in final_trades:
            if not isinstance(trade, dict):
                continue
            lines.append(
                f"- {trade.get('ticker')}: entry {_fmt_price(trade.get('entry_price'))}, "
                f"target {_fmt_price(trade.get('target_price'))}, stop {_fmt_price(trade.get('stop_loss'))}, "
                f"R/R {_fmt_num(trade.get('risk_reward'))}"
            )
    else:
        lines.extend(["", "No final paper trades qualified."])
    watchlist = _as_list(payload.get("watchlist"))
    if watchlist:
        lines.extend(["", "Watchlist:"])
        for item in watchlist[:8]:
            if isinstance(item, dict):
                lines.append(f"- {item.get('ticker')}: {item.get('reason') or item.get('summary') or 'watchlist only'}")
    warnings = _as_list(payload.get("risk_warnings")) + _as_list(payload.get("data_quality_warnings"))
    if warnings:
        lines.extend(["", "Warnings:"])
        for warning in warnings[:10]:
            lines.append(f"- {warning}")
    return "\n".join(lines).strip()


def format_deterministic_fallback_response(
    trading_brain_result: dict,
    config: dict | None = None,
) -> str:
    result = trading_brain_result if isinstance(trading_brain_result, dict) else {}
    facts = extract_grounding_facts(result)
    decision = result.get("decision_result") if isinstance(result.get("decision_result"), dict) else {}
    selection = result.get("selection_result") if isinstance(result.get("selection_result"), dict) else {}
    summary = result.get("summary") if isinstance(result.get("summary"), dict) else {}
    final_trades = _as_list(decision.get("final_recommendations"))
    watchlist = _as_list(selection.get("watchlist_alternatives"))
    rejected = _as_list(selection.get("rejected_candidates")) + _as_list(decision.get("not_selected"))

    lines = [
        summary.get("message") or "Deterministic trading-brain fallback summary.",
        "",
        "Paper trading only. This is simulated research output, not real brokerage execution.",
        f"Selected count: {facts.get('selected_count', 0)}. Logged count: {facts.get('logged_count', 0)}.",
    ]
    if final_trades:
        lines.extend(["", "Final Paper Trades:"])
        for trade in final_trades:
            if not isinstance(trade, dict):
                continue
            lines.append(
                f"- {trade.get('ticker')}: entry {_fmt_price(trade.get('entry_price'))}, "
                f"target {_fmt_price(trade.get('target_price'))}, stop {_fmt_price(trade.get('stop_loss'))}, "
                f"R/R {_fmt_num(trade.get('risk_reward'))}; {trade.get('thesis') or 'passed deterministic constraints'}"
            )
    else:
        lines.extend(["", "No final paper trades qualified."])
    if watchlist:
        lines.extend(["", "Watchlist:"])
        for item in watchlist[:8]:
            if isinstance(item, dict):
                lines.append(f"- {item.get('ticker')}: {item.get('downgrade_reason') or item.get('rejection_reason') or item.get('recommendation_status') or 'watchlist only'}")
    if rejected:
        lines.extend(["", "Rejected / Not Selected:"])
        for item in rejected[:8]:
            if isinstance(item, dict):
                ticker = item.get("ticker") or ((item.get("candidate") or {}).get("ticker") if isinstance(item.get("candidate"), dict) else "Unknown")
                reason = item.get("reason") or item.get("rejection_reason") or "did not pass deterministic guardrails"
                lines.append(f"- {ticker}: {reason}")
    option_status = facts.get("options_status", {})
    if option_status.get("options_included"):
        lines.extend(["", "Options:"])
        lines.append("- Options remain research-only or blocked unless the deterministic option gates mark them paper_eligible.")
    warnings = facts.get("risk_warnings", []) + facts.get("data_quality_warnings", [])
    if warnings:
        lines.extend(["", "Warnings:"])
        for warning in warnings[:10]:
            lines.append(f"- {warning}")
    return "\n".join(lines).strip()
