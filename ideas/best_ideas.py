from __future__ import annotations

from copy import deepcopy
from typing import Any


def _as_dict(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list:
    return value if isinstance(value, list) else []


def _safe_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _first_text(*values: Any) -> str:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, list) and value:
            joined = "; ".join(str(item) for item in value if item)
            if joined:
                return joined
    return ""


def _unique_by_key(items: list[dict], key_name: str = "idea_key") -> list[dict]:
    seen: set[str] = set()
    unique: list[dict] = []
    for item in items:
        key = str(item.get(key_name) or item.get("ticker") or item.get("option_contract") or id(item))
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique


def _score_candidate(candidate: dict) -> float:
    score = _safe_float(candidate.get("score")) or 0.0
    rr = _safe_float(candidate.get("risk_reward"))
    if rr is not None:
        score += min(max(rr, 0.0), 5.0) * 2.0

    status = str(candidate.get("recommendation_status") or candidate.get("status") or "").lower()
    if status in {"recommendable", "paper_eligible"}:
        score += 20
    elif status == "watchlist":
        score += 10

    quality_bucket = str(candidate.get("quality_bucket", "")).upper()
    if quality_bucket == "A+":
        score += 8
    elif quality_bucket == "A":
        score += 6
    elif quality_bucket == "B":
        score += 3

    relative_strength = _as_dict(candidate.get("relative_strength_context"))
    rs_label = str(relative_strength.get("relative_strength_label", "")).lower()
    if rs_label in {"market_leader", "outperforming"}:
        score += 5
    elif rs_label in {"underperforming", "market_laggard"}:
        score -= 5

    technical = _as_dict(candidate.get("technical_confirmation_summary"))
    technical_status = str(technical.get("status", "")).lower()
    if technical_status in {"confirmed", "pass", "passed"}:
        score += 5
    elif technical_status in {"warning", "watchlist"}:
        score += 2
    elif technical_status == "rejected":
        score -= 8

    return round(score, 2)


def _candidate_reason(candidate: dict) -> str:
    return _first_text(
        candidate.get("thesis"),
        candidate.get("selection_reason"),
        candidate.get("reason"),
        candidate.get("rejection_reason"),
        candidate.get("invalidation"),
        candidate.get("why_this_profile_matched"),
        candidate.get("failed_constraints"),
    )


def _compact_candidate(candidate: dict, bucket: str, source: str) -> dict:
    ticker = str(candidate.get("ticker") or candidate.get("underlying_ticker") or "").upper()
    status = str(candidate.get("recommendation_status") or candidate.get("status") or bucket).lower()
    failed_constraints = _as_list(candidate.get("failed_constraints"))
    data_quality = _as_dict(candidate.get("data_quality"))
    idea_score = _score_candidate(candidate)
    return {
        "idea_key": f"{bucket}:{source}:{ticker}:{candidate.get('option_contract') or ''}",
        "ticker": ticker,
        "asset_type": candidate.get("asset_type", "stock"),
        "direction": candidate.get("direction", "long"),
        "strategy": candidate.get("strategy"),
        "setup_type": candidate.get("setup_type") or candidate.get("scan_profile"),
        "recommendation_status": status,
        "bucket": bucket,
        "source": source,
        "score": candidate.get("score"),
        "idea_score": idea_score,
        "risk_reward": candidate.get("risk_reward"),
        "entry_price": candidate.get("entry_price"),
        "target_price": candidate.get("target_price"),
        "stop_loss": candidate.get("stop_loss"),
        "reason": _candidate_reason(candidate),
        "failed_constraints": failed_constraints,
        "rejection_reason": candidate.get("rejection_reason"),
        "quality_bucket": candidate.get("quality_bucket"),
        "relative_strength": _as_dict(candidate.get("relative_strength_context")).get("relative_strength_label"),
        "data_quality": data_quality.get("quality_label"),
        "raw_candidate": deepcopy(candidate),
    }


def _compact_option(candidate: dict, bucket: str, source: str) -> dict:
    risk = _as_dict(candidate.get("option_trade_risk"))
    iv = _as_dict(candidate.get("iv_context"))
    greeks = _as_dict(candidate.get("greeks_monitoring") or candidate.get("greeks"))
    status = str(candidate.get("recommendation_status") or risk.get("status") or candidate.get("status") or bucket).lower()
    missing = []
    for label, value in (
        ("option chain", candidate.get("option_contract")),
        ("bid/ask", candidate.get("bid") if candidate.get("bid") is not None else candidate.get("ask")),
        ("IV", iv.get("implied_volatility") if iv else candidate.get("implied_volatility")),
        ("Greeks", greeks.get("delta") if greeks else candidate.get("delta")),
        ("fill quality", risk.get("fill_quality") or candidate.get("fill_quality")),
    ):
        if value in (None, "", []):
            missing.append(label)

    ticker = str(candidate.get("underlying_ticker") or candidate.get("ticker") or "").upper()
    return {
        "idea_key": f"{bucket}:{source}:{ticker}:{candidate.get('option_contract') or candidate.get('strategy_type') or ''}",
        "ticker": ticker,
        "asset_type": "option",
        "strategy": candidate.get("strategy_type") or candidate.get("strategy") or "option_research",
        "option_contract": candidate.get("option_contract"),
        "expiration": candidate.get("expiration"),
        "recommendation_status": status,
        "bucket": bucket,
        "source": source,
        "score": candidate.get("score"),
        "idea_score": _score_candidate(candidate),
        "bid": candidate.get("bid"),
        "ask": candidate.get("ask"),
        "mid": candidate.get("mid"),
        "days_to_expiration": candidate.get("days_to_expiration"),
        "iv_rank": iv.get("iv_rank") if iv else candidate.get("iv_rank"),
        "greeks_quality": greeks.get("greeks_quality") if greeks else candidate.get("greeks_quality"),
        "reason": _first_text(candidate.get("reason"), risk.get("reason"), risk.get("block_reason"), candidate.get("selection_reason"), candidate.get("rejection_reason")),
        "missing_requirements": missing,
        "raw_candidate": deepcopy(candidate),
    }


def _collect_path(root: dict, path: tuple[str, ...]) -> Any:
    current: Any = root
    for part in path:
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return current


def _candidate_lists(root: dict, paths: list[tuple[str, ...]]) -> list[dict]:
    rows: list[dict] = []
    for path in paths:
        value = _collect_path(root, path)
        rows.extend(item for item in _as_list(value) if isinstance(item, dict))
    return rows


def _detect_system_issues(root: dict) -> tuple[list[str], list[str]]:
    data_missing: list[str] = []
    system_issues: list[str] = []
    text = str(root)
    if "Connect call failed" in text or "ConnectionRefusedError" in text:
        system_issues.append("IBKR/TWS is not reachable on 127.0.0.1:7496. Live quotes/options data are unavailable.")
    if "Cannot run the event loop" in text or "There is no current event loop" in text:
        system_issues.append("Backend event-loop bridge issue detected. Retry after API bridge fix is deployed.")
    if "Option chain is empty or malformed" in text:
        data_missing.append("Option chain is empty or malformed.")
    if "option quotes" in text.lower() or "opra" in text.lower():
        data_missing.append("Option quote/OPRA permissions may be missing.")
    if "Latest historical bar is stale" in text and "latest_completed_session" not in text:
        data_missing.append("Historical bars are older than the latest expected completed market session.")

    startup_readiness = _as_dict(root.get("startup_readiness") or _collect_path(root, ("trade_hunt", "startup_readiness")))
    if startup_readiness and startup_readiness.get("ok") is False:
        for error in _as_list(startup_readiness.get("errors")):
            system_issues.append(str(error))
        if not startup_readiness.get("errors"):
            for warning in _as_list(startup_readiness.get("warnings")):
                system_issues.append(str(warning))

    scan_result = _as_dict(root.get("scan_result") or _collect_path(root, ("trade_hunt", "scan_result")))
    data_quality = _as_dict(scan_result.get("data_quality_summary"))
    for warning in _as_list(data_quality.get("warnings")):
        data_missing.append(str(warning))
    for error in _as_list(data_quality.get("errors")):
        data_missing.append(str(error))
    return list(dict.fromkeys(data_missing)), list(dict.fromkeys(system_issues))


def build_best_available_ideas(
    trading_result: dict,
    max_stock_ideas: int = 5,
    max_option_ideas: int = 5,
    config: dict | None = None,
) -> dict:
    config = config or {}
    include_options = bool(config.get("include_options", True))
    root = trading_result if isinstance(trading_result, dict) else {}
    trade_hunt = _as_dict(root.get("trade_hunt"))
    scan_root = trade_hunt or root

    final_candidates = _candidate_lists(
        scan_root,
        [
            ("decision_result", "final_recommendations"),
            ("paper_trades_logged",),
        ],
    )
    paper_eligible = [_compact_candidate(item, "paper_eligible", "strict_final") for item in final_candidates]

    watchlist_candidates = _candidate_lists(
        scan_root,
        [
            ("selection_result", "watchlist_alternatives"),
            ("decision_result", "watchlist"),
            ("scan_result", "watchlist_candidates"),
        ],
    )
    stock_watchlist = [_compact_candidate(item, "watchlist", "near_miss") for item in watchlist_candidates if str(item.get("asset_type", "stock")).lower() != "option"]

    rejected_candidates = _candidate_lists(
        scan_root,
        [
            ("selection_result", "rejected_candidates"),
            ("scan_result", "rejected_candidates"),
            ("decision_result", "risk_rejected"),
        ],
    )
    not_selected = _candidate_lists(scan_root, [("decision_result", "not_selected")])
    for row in not_selected:
        candidate = row.get("candidate") if isinstance(row.get("candidate"), dict) else row
        if isinstance(candidate, dict):
            candidate = deepcopy(candidate)
            candidate.setdefault("rejection_reason", row.get("reason"))
            rejected_candidates.append(candidate)

    blocked_but_interesting = [_compact_candidate(item, "blocked_but_interesting", "strict_reject") for item in rejected_candidates if str(item.get("asset_type", "stock")).lower() != "option"]

    option_candidates: list[dict] = []
    if include_options:
        option_research = _as_dict(scan_root.get("option_research"))
        for key in ("best_option_candidates", "watchlist_option_candidates", "rejected_option_candidates"):
            option_candidates.extend(item for item in _as_list(option_research.get(key)) if isinstance(item, dict))
        for stock in _candidate_lists(scan_root, [("selection_result", "selected_trades"), ("selection_result", "watchlist_alternatives")]):
            option_candidates.extend(item for item in _as_list(stock.get("option_strategy_candidates")) if isinstance(item, dict))
            option_candidates.extend(item for item in _as_list(stock.get("option_alternatives")) if isinstance(item, dict))

    option_research_only: list[dict] = []
    option_blocked: list[dict] = []
    for option in option_candidates:
        status = str(option.get("recommendation_status") or _as_dict(option.get("option_trade_risk")).get("status") or option.get("status") or "").lower()
        compact = _compact_option(option, "research_only" if status != "blocked" else "blocked_but_interesting", "option_research")
        if status == "blocked" or compact["missing_requirements"]:
            option_blocked.append(compact)
        else:
            option_research_only.append(compact)

    data_missing, system_issues = _detect_system_issues(scan_root)
    if not include_options:
        data_missing = [item for item in data_missing if "option" not in item.lower() and "opra" not in item.lower()]
        system_issues = [item for item in system_issues if "option" not in item.lower()]
    if include_options and option_blocked and not any("option" in item.lower() for item in data_missing):
        data_missing.append("Some option candidates are missing quote, IV, Greeks, or fill-quality data.")

    paper_eligible = sorted(_unique_by_key(paper_eligible), key=lambda item: item.get("idea_score", 0), reverse=True)
    stock_watchlist = sorted(_unique_by_key(stock_watchlist), key=lambda item: item.get("idea_score", 0), reverse=True)[:max_stock_ideas]
    option_research_only = sorted(_unique_by_key(option_research_only), key=lambda item: item.get("idea_score", 0), reverse=True)[:max_option_ideas]
    blocked_but_interesting = sorted(_unique_by_key(blocked_but_interesting + option_blocked), key=lambda item: item.get("idea_score", 0), reverse=True)[: max_stock_ideas + max_option_ideas]

    why_no_final_trades: list[str] = []
    if not paper_eligible:
        why_no_final_trades.append("No final paper trades passed strict objective gates.")
        if stock_watchlist:
            why_no_final_trades.append("Some stocks were close enough for watchlist review, but not final logging.")
        if blocked_but_interesting:
            why_no_final_trades.append("Some candidates had interesting attributes but were blocked by data quality, risk, macro, portfolio, or option constraints.")
        if not stock_watchlist and not blocked_but_interesting and not option_research_only:
            why_no_final_trades.append("The scan did not return enough usable candidate data to rank near-misses.")

    next_steps = []
    if system_issues:
        next_steps.append("Fix system/provider connectivity first, then rerun the scan.")
    if data_missing:
        next_steps.append("Resolve missing market/options data before treating research ideas as actionable.")
    if stock_watchlist:
        next_steps.append("Monitor watchlist ideas for fresh price/volume confirmation and risk/reward improvement.")
    if include_options and (option_research_only or option_blocked):
        next_steps.append("For options, verify option chain, bid/ask, IV, Greeks, DTE, spread, and fill quality.")
    if not next_steps:
        next_steps.append("Review strict paper-eligible trades and confirm they are simulated-only before logging.")

    summary = (
        f"{len(paper_eligible)} paper-eligible, {len(stock_watchlist)} stock watchlist, "
        f"{len(option_research_only)} option research-only, {len(blocked_but_interesting)} blocked-but-interesting ideas."
    )

    return {
        "ok": True,
        "paper_trading_only": True,
        "summary": summary,
        "paper_eligible": paper_eligible,
        "stock_watchlist": stock_watchlist,
        "option_research_only": option_research_only,
        "blocked_but_interesting": blocked_but_interesting,
        "why_no_final_trades": why_no_final_trades,
        "data_missing": list(dict.fromkeys(data_missing)),
        "system_issues": list(dict.fromkeys(system_issues)),
        "next_steps": list(dict.fromkeys(next_steps)),
        "warnings": [
            "Best Available Ideas is an explanatory ranking layer only.",
            "Only paper_eligible ideas may be logged as simulated paper trades by existing backend guardrails.",
        ],
    }
