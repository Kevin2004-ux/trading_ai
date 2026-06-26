from __future__ import annotations

from copy import deepcopy
from typing import Any

from .data_failures import extend_issues_from_failures, split_data_failures
from .option_opportunity_ranker import score_option_opportunity
from .opportunity_ranker import score_stock_opportunity

_DATA_FAILURE_CONSTRAINTS = {
    "scanner_error",
    "provider_error",
    "data_provider_error",
    "data_retrieval_error",
    "market_data_error",
    "market_data_unavailable",
    "historical_bars_unavailable",
    "quote_unavailable",
    "option_quotes_unavailable",
}

_STRONG_PROVIDER_FAILURE_TEXT = (
    "connect call failed",
    "connectionrefusederror",
    "connection refused",
    "errno 61",
    "tws is not reachable",
    "tws/ibkr is not reachable",
    "ibkr/tws is not reachable",
    "ibkr historical bars unavailable",
    "historical bars unavailable",
    "market data could not be retrieved",
    "could not retrieve market data",
    "market data unavailable",
    "provider unavailable",
    "scanner_error",
)

_WEAK_DATA_FAILURE_TEXT = (
    "quote unavailable",
    "quotes unavailable",
    "option chain unavailable",
    "option quotes unavailable",
    "empty api response",
    "empty response",
    "malformed ohlcv",
    "missing ohlcv",
    "no usable market data",
)


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


def _string_values(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        rows: list[str] = []
        for nested in value.values():
            rows.extend(_string_values(nested))
        return rows
    if isinstance(value, list):
        rows: list[str] = []
        for nested in value:
            rows.extend(_string_values(nested))
        return rows
    return []


def _normalized_text(value: Any) -> str:
    return " | ".join(_string_values(value)).lower()


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


def _has_positive_number(*values: Any) -> bool:
    for value in values:
        number = _safe_float(value)
        if number is not None and number > 0:
            return True
    return False


def _has_usable_technical_snapshot(candidate: dict) -> bool:
    technical = _as_dict(candidate.get("technical_snapshot") or candidate.get("technical"))
    if not technical:
        return False
    useful_fields = (
        "current_price",
        "previous_close",
        "daily_return",
        "sma_20",
        "sma_50",
        "rsi_14",
        "average_volume_20",
        "relative_volume",
        "atr_14",
        "atr_percent",
    )
    return any(technical.get(field) not in (None, "", [], {}) for field in useful_fields)


def _has_trade_prices(candidate: dict) -> bool:
    return _has_positive_number(
        candidate.get("current_price"),
        candidate.get("entry_price"),
        candidate.get("target_price"),
        candidate.get("stop_loss"),
        _as_dict(candidate.get("technical_snapshot")).get("current_price"),
    )


def _has_option_quote_data(candidate: dict) -> bool:
    return _has_positive_number(
        candidate.get("bid"),
        candidate.get("ask"),
        candidate.get("mid"),
        candidate.get("last"),
        candidate.get("close"),
    )


def _constraint_values(candidate: dict) -> set[str]:
    values: set[str] = set()
    for key in ("failed_constraints", "errors", "error_codes"):
        raw = candidate.get(key)
        if isinstance(raw, list):
            values.update(str(item).strip().lower() for item in raw if str(item).strip())
        elif isinstance(raw, str) and raw.strip():
            values.add(raw.strip().lower())

    constraint_results = _as_dict(candidate.get("constraint_results"))
    for key in ("failed_constraints", "errors"):
        raw = constraint_results.get(key)
        if isinstance(raw, list):
            values.update(str(item).strip().lower() for item in raw if str(item).strip())
        elif isinstance(raw, str) and raw.strip():
            values.add(raw.strip().lower())
    return values


def _is_data_failure_candidate(candidate: dict) -> bool:
    if not isinstance(candidate, dict):
        return False

    data_quality = _as_dict(candidate.get("data_quality"))
    constraint_values = _constraint_values(candidate)
    if constraint_values.intersection(_DATA_FAILURE_CONSTRAINTS):
        return True

    quality_label = str(data_quality.get("quality_label") or "").strip().lower()
    if quality_label == "unavailable":
        return True

    text = _normalized_text(
        {
            "candidate_errors": candidate.get("errors"),
            "candidate_error": candidate.get("error"),
            "rejection_reason": candidate.get("rejection_reason"),
            "reason": candidate.get("reason"),
            "data_quality": data_quality,
            "market_snapshot": candidate.get("market_snapshot"),
            "provider_status": candidate.get("provider_status"),
        }
    )
    if any(pattern in text for pattern in _STRONG_PROVIDER_FAILURE_TEXT):
        return True

    has_price = _has_trade_prices(candidate)
    has_technical = _has_usable_technical_snapshot(candidate)
    has_option_quote = _has_option_quote_data(candidate)
    has_weak_provider_text = any(pattern in text for pattern in _WEAK_DATA_FAILURE_TEXT)

    if data_quality.get("ok") is False and has_weak_provider_text:
        return True
    if has_weak_provider_text and not (has_price or has_technical or has_option_quote):
        return True
    return False


def _candidate_failure_issues(candidate: dict) -> tuple[list[str], list[str]]:
    data_missing: list[str] = []
    system_issues: list[str] = []
    text = _normalized_text(candidate)
    data_quality = _as_dict(candidate.get("data_quality"))

    if any(pattern in text for pattern in ("connect call failed", "connectionrefusederror", "connection refused", "errno 61", "tws is not reachable", "ibkr/tws is not reachable")):
        system_issues.append("IBKR/TWS is not reachable on 127.0.0.1:7496. Live market data is unavailable.")
    if "historical bars unavailable" in text:
        data_missing.append("Historical bars are unavailable from the configured market-data provider.")
    if "quote unavailable" in text or "quotes unavailable" in text:
        data_missing.append("Live quote data is unavailable from the configured market-data provider.")
    if "option chain unavailable" in text or "option quotes unavailable" in text:
        data_missing.append("Option chain/quote data is unavailable from the configured options provider.")
    if data_quality.get("quality_label") == "unavailable" or "scanner_error" in _constraint_values(candidate):
        data_missing.append("Scanner/provider failures returned no usable market data for one or more candidates.")
    if not data_missing and not system_issues:
        data_missing.append("Usable market data was not returned for one or more candidates.")
    return data_missing, system_issues


def _split_data_failures(candidates: list[dict]) -> tuple[list[dict], list[dict]]:
    usable: list[dict] = []
    failures: list[dict] = []
    for candidate in candidates:
        if _is_data_failure_candidate(candidate):
            failures.append(candidate)
        else:
            usable.append(candidate)
    return usable, failures


def _extend_issues_from_failures(data_missing: list[str], system_issues: list[str], failures: list[dict]) -> None:
    for failure in failures:
        missing, issues = _candidate_failure_issues(failure)
        data_missing.extend(missing)
        system_issues.extend(issues)


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


def _compact_candidate(candidate: dict, bucket: str, source: str, opportunity_config: dict | None = None) -> dict:
    ticker = str(candidate.get("ticker") or candidate.get("underlying_ticker") or "").upper()
    status = str(candidate.get("recommendation_status") or candidate.get("status") or bucket).lower()
    failed_constraints = _as_list(candidate.get("failed_constraints"))
    data_quality = _as_dict(candidate.get("data_quality"))
    idea_score = _score_candidate(candidate)
    opportunity = score_stock_opportunity(candidate, config=opportunity_config)
    compact = {
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
    compact.update(
        {
            "opportunity_score": opportunity.get("opportunity_score"),
            "opportunity_score_version": opportunity.get("score_version"),
            "opportunity_components": opportunity.get("components", {}),
            "data_confidence": opportunity.get("data_confidence"),
            "why_ranked": opportunity.get("why_ranked", []),
            "key_risks": opportunity.get("key_risks", []),
            "confirmation_needed": opportunity.get("confirmation_needed", []),
            "qualification_gaps": opportunity.get("qualification_gaps", []),
            "actionability_status": opportunity.get("actionability_status"),
        }
    )
    return compact


def _compact_option(candidate: dict, bucket: str, source: str, opportunity_config: dict | None = None) -> dict:
    risk = _as_dict(candidate.get("option_trade_risk"))
    iv = _as_dict(candidate.get("iv_context"))
    greeks = _as_dict(candidate.get("greeks_monitoring") or candidate.get("greeks"))
    status = str(candidate.get("recommendation_status") or risk.get("status") or candidate.get("status") or bucket).lower()
    opportunity = score_option_opportunity(
        candidate,
        underlying_candidate=_as_dict(candidate.get("underlying_candidate") or candidate.get("underlying_view")),
        config=opportunity_config,
    )
    missing = list(_as_list(candidate.get("missing_requirements"))) + list(_as_list(opportunity.get("missing_requirements")))
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
    opportunity_score = candidate.get("option_opportunity_score")
    if opportunity_score is None:
        opportunity_score = opportunity.get("opportunity_score")
    idea_score = opportunity_score if opportunity_score is not None else _score_candidate(candidate)
    delta = candidate.get("delta") if candidate.get("delta") is not None else greeks.get("delta")
    return {
        "idea_key": f"{bucket}:{source}:{ticker}:{candidate.get('option_contract') or candidate.get('strategy_type') or ''}",
        "ticker": ticker,
        "asset_type": "option",
        "strategy": candidate.get("strategy_type") or candidate.get("strategy") or "option_research",
        "option_contract": candidate.get("option_contract"),
        "option_type": candidate.get("option_type"),
        "strike": candidate.get("strike"),
        "expiration": candidate.get("expiration"),
        "recommendation_status": status,
        "bucket": bucket,
        "source": source,
        "score": candidate.get("score"),
        "idea_score": idea_score,
        "option_opportunity_score": opportunity_score,
        "option_opportunity_score_version": candidate.get("option_opportunity_score_version") or opportunity.get("score_version"),
        "option_opportunity_components": candidate.get("option_opportunity_components") or opportunity.get("components", {}),
        "option_data_confidence": candidate.get("option_data_confidence") if candidate.get("option_data_confidence") is not None else opportunity.get("data_confidence"),
        "bid": candidate.get("bid"),
        "ask": candidate.get("ask"),
        "mid": candidate.get("mid"),
        "spread_percent": candidate.get("spread_percent"),
        "open_interest": candidate.get("open_interest"),
        "volume": candidate.get("volume"),
        "implied_volatility": candidate.get("implied_volatility") or candidate.get("iv"),
        "days_to_expiration": candidate.get("days_to_expiration"),
        "iv_rank": iv.get("iv_rank") if iv else candidate.get("iv_rank"),
        "delta": delta,
        "breakeven_price": candidate.get("breakeven_price") or candidate.get("breakeven"),
        "risk_reward": candidate.get("risk_reward"),
        "underlying_status": candidate.get("underlying_status"),
        "underlying_opportunity_score": candidate.get("underlying_opportunity_score"),
        "greeks_quality": greeks.get("greeks_quality") if greeks else candidate.get("greeks_quality"),
        "reason": _first_text(candidate.get("reason"), risk.get("reason"), risk.get("block_reason"), candidate.get("selection_reason"), candidate.get("rejection_reason")),
        "why_ranked": _as_list(candidate.get("why_ranked")) or _as_list(opportunity.get("why_ranked")),
        "key_risks": _as_list(candidate.get("key_risks")) or _as_list(opportunity.get("key_risks")),
        "missing_requirements": list(dict.fromkeys(missing)),
        "qualification_gaps": _as_list(candidate.get("qualification_gaps")) or _as_list(opportunity.get("qualification_gaps")),
        "raw_candidate": deepcopy(candidate),
    }


def _compact_underlying_watchlist(row: dict) -> dict:
    return {
        "idea_key": f"option_underlying_watchlist:{str(row.get('ticker') or '').upper()}",
        "ticker": str(row.get("ticker") or "").upper(),
        "asset_type": "option_underlying",
        "option_bias": row.get("option_bias"),
        "underlying_opportunity_score": row.get("underlying_opportunity_score"),
        "underlying_status": row.get("underlying_status"),
        "why_watch": list(_as_list(row.get("why_watch"))),
        "required_before_contract_ranking": list(_as_list(row.get("required_before_contract_ranking"))),
        "paper_trading_only": True,
        "raw_candidate": deepcopy(row),
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
    data_missing.extend(str(item) for item in _as_list(root.get("adaptive_data_missing")) if item)
    system_issues.extend(str(item) for item in _as_list(root.get("adaptive_system_issues")) if item)
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


def _extend_option_discovery_issues(option_discovery: dict, data_missing: list[str], system_issues: list[str]) -> None:
    if not option_discovery:
        return
    for item in _as_list(option_discovery.get("missing_requirements")):
        data_missing.append(str(item))
    for item in _as_list(option_discovery.get("warnings")):
        if "tws" in str(item).lower() or "connection" in str(item).lower():
            system_issues.append(str(item))
        else:
            data_missing.append(str(item))
    for item in _as_list(option_discovery.get("errors")):
        text = str(item)
        if any(token in text.lower() for token in ("tws", "ibkr", "connect", "connection", "errno 61")):
            system_issues.append(text)
        else:
            data_missing.append(text)


def _stock_sort_key(item: dict) -> tuple[float, float, float]:
    opportunity = _safe_float(item.get("opportunity_score"))
    engine = _safe_float(item.get("score"))
    risk_reward = _safe_float(item.get("risk_reward"))
    return (
        opportunity if opportunity is not None else -1.0,
        engine if engine is not None else -1.0,
        risk_reward if risk_reward is not None else -1.0,
    )


def build_best_available_ideas(
    trading_result: dict,
    max_stock_ideas: int = 5,
    max_option_ideas: int = 5,
    config: dict | None = None,
) -> dict:
    config = config or {}
    include_options = bool(config.get("include_options", True))
    opportunity_config = config.get("opportunity_ranker") if isinstance(config.get("opportunity_ranker"), dict) else None
    root = trading_result if isinstance(trading_result, dict) else {}
    trade_hunt = _as_dict(root.get("trade_hunt"))
    scan_root = trade_hunt or root
    option_discovery = _as_dict(config.get("option_discovery") or root.get("option_discovery") or scan_root.get("option_discovery"))

    final_candidates = _candidate_lists(
        scan_root,
        [
            ("decision_result", "final_recommendations"),
            ("paper_trades_logged",),
        ],
    )
    final_candidates, final_failures = split_data_failures(final_candidates)
    paper_eligible = [_compact_candidate(item, "paper_eligible", "strict_final", opportunity_config=opportunity_config) for item in final_candidates]

    watchlist_candidates = _candidate_lists(
        scan_root,
        [
            ("selection_result", "watchlist_alternatives"),
            ("decision_result", "watchlist"),
            ("scan_result", "watchlist_candidates"),
        ],
    )
    watchlist_candidates, watchlist_failures = split_data_failures(watchlist_candidates)
    stock_watchlist = [_compact_candidate(item, "watchlist", "near_miss", opportunity_config=opportunity_config) for item in watchlist_candidates if str(item.get("asset_type", "stock")).lower() != "option"]

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

    rejected_candidates, rejected_failures = split_data_failures(rejected_candidates)
    blocked_but_interesting = [_compact_candidate(item, "blocked_but_interesting", "strict_reject", opportunity_config=opportunity_config) for item in rejected_candidates if str(item.get("asset_type", "stock")).lower() != "option"]

    option_candidates: list[dict] = []
    option_paper_eligible_candidates: list[dict] = []
    option_underlying_watchlist: list[dict] = []
    if include_options:
        option_research = _as_dict(scan_root.get("option_research"))
        for key in ("best_option_candidates", "watchlist_option_candidates", "rejected_option_candidates"):
            option_candidates.extend(item for item in _as_list(option_research.get(key)) if isinstance(item, dict))
        for stock in _candidate_lists(scan_root, [("selection_result", "selected_trades"), ("selection_result", "watchlist_alternatives")]):
            option_candidates.extend(item for item in _as_list(stock.get("option_strategy_candidates")) if isinstance(item, dict))
            option_candidates.extend(item for item in _as_list(stock.get("option_alternatives")) if isinstance(item, dict))
        option_paper_eligible_candidates.extend(
            item for item in _as_list(option_discovery.get("paper_eligible_contracts")) if isinstance(item, dict)
        )
        option_candidates.extend(
            item for item in _as_list(option_discovery.get("research_only_contracts")) if isinstance(item, dict)
        )
        option_candidates.extend(
            item for item in _as_list(option_discovery.get("blocked_contracts")) if isinstance(item, dict)
        )
        option_underlying_watchlist = [
            _compact_underlying_watchlist(item)
            for item in _as_list(option_discovery.get("underlying_watchlist"))
            if isinstance(item, dict)
        ]

    option_candidates, option_failures = split_data_failures(option_candidates)
    option_paper_eligible_candidates, option_paper_failures = split_data_failures(option_paper_eligible_candidates)
    data_failure_candidates = final_failures + watchlist_failures + rejected_failures + option_failures
    data_failure_candidates += option_paper_failures
    usable_candidate_count = (
        len(final_candidates)
        + len(watchlist_candidates)
        + len(rejected_candidates)
        + len(option_candidates)
        + len(option_paper_eligible_candidates)
        + len(option_underlying_watchlist)
    )

    option_research_only: list[dict] = []
    option_blocked: list[dict] = []
    option_paper_eligible = [
        _compact_option(option, "paper_eligible", "option_discovery", opportunity_config=opportunity_config)
        for option in option_paper_eligible_candidates
    ]
    for option in option_candidates:
        status = str(option.get("recommendation_status") or _as_dict(option.get("option_trade_risk")).get("status") or option.get("status") or "").lower()
        compact = _compact_option(option, "research_only" if status not in {"blocked", "rejected"} else "blocked_but_interesting", "option_research", opportunity_config=opportunity_config)
        if status in {"blocked", "rejected"}:
            option_blocked.append(compact)
        else:
            option_research_only.append(compact)

    data_missing, system_issues = _detect_system_issues(scan_root)
    extend_issues_from_failures(data_missing, system_issues, data_failure_candidates)
    if include_options:
        _extend_option_discovery_issues(option_discovery, data_missing, system_issues)
    if not include_options:
        data_missing = [item for item in data_missing if "option" not in item.lower() and "opra" not in item.lower()]
        system_issues = [item for item in system_issues if "option" not in item.lower()]
    if include_options and option_blocked and not any("option" in item.lower() for item in data_missing):
        data_missing.append("Some option candidates are missing quote, IV, Greeks, or fill-quality data.")

    paper_eligible = sorted(_unique_by_key(paper_eligible), key=_stock_sort_key, reverse=True)
    option_paper_eligible = sorted(_unique_by_key(option_paper_eligible), key=lambda item: (_safe_float(item.get("option_opportunity_score")) or -1.0, _safe_float(item.get("score")) or -1.0), reverse=True)
    paper_eligible = paper_eligible + option_paper_eligible
    stock_watchlist = sorted(_unique_by_key(stock_watchlist), key=_stock_sort_key, reverse=True)[:max_stock_ideas]
    option_research_only = sorted(
        _unique_by_key(option_research_only),
        key=lambda item: (
            _safe_float(item.get("option_opportunity_score")) if item.get("option_opportunity_score") is not None else -1.0,
            _safe_float(item.get("score")) or -1.0,
            _safe_float(item.get("risk_reward")) or -1.0,
            -(_safe_float(item.get("spread_percent")) or 999.0),
        ),
        reverse=True,
    )[:max_option_ideas]
    stock_blocked = sorted(_unique_by_key(blocked_but_interesting), key=_stock_sort_key, reverse=True)
    option_blocked = sorted(
        _unique_by_key(option_blocked),
        key=lambda item: (
            _safe_float(item.get("option_opportunity_score")) if item.get("option_opportunity_score") is not None else -1.0,
            _safe_float(item.get("score")) or -1.0,
            _safe_float(item.get("risk_reward")) or -1.0,
            -(_safe_float(item.get("spread_percent")) or 999.0),
        ),
        reverse=True,
    )
    option_underlying_watchlist = sorted(
        _unique_by_key(option_underlying_watchlist),
        key=lambda item: _safe_float(item.get("underlying_opportunity_score")) or -1.0,
        reverse=True,
    )[:max_option_ideas]
    blocked_but_interesting = (stock_blocked + option_blocked)[: max_stock_ideas + max_option_ideas]

    ranked_candidate_count = len(paper_eligible) + len(stock_watchlist) + len(option_research_only) + len(blocked_but_interesting) + len(option_underlying_watchlist)
    if ranked_candidate_count:
        ranking_status = "available"
    elif data_failure_candidates and usable_candidate_count == 0:
        ranking_status = "unavailable"
    elif not usable_candidate_count and (data_missing or system_issues):
        ranking_status = "unavailable"
    else:
        ranking_status = "no_qualifying_ideas"

    why_no_final_trades: list[str] = []
    if not paper_eligible:
        why_no_final_trades.append("No final paper trades passed strict objective gates.")
        if ranking_status == "unavailable":
            why_no_final_trades.append("Market ranking is unavailable because the scan did not return usable market data.")
        if stock_watchlist:
            why_no_final_trades.append("Some stocks were close enough for watchlist review, but not final logging.")
        if blocked_but_interesting:
            why_no_final_trades.append("Some candidates had usable market data but were blocked by risk, macro, portfolio, technical, or option constraints.")
        if option_underlying_watchlist and not option_research_only:
            why_no_final_trades.append("Some underlyings are worth option research, but exact contract ranking needs usable bid/ask, IV, Greeks, liquidity, and fill-quality data.")
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
    if include_options and option_underlying_watchlist and not option_research_only:
        next_steps.append("Restore option quote/OPRA data, then rerun option discovery for exact contract ranking.")
    if not next_steps:
        next_steps.append("Review strict paper-eligible trades and confirm they are simulated-only before logging.")

    summary = (
        f"{len(paper_eligible)} paper-eligible, {len(stock_watchlist)} stock watchlist, "
        f"{len(option_research_only)} option research-only, {len(blocked_but_interesting)} blocked-but-interesting ideas, "
        f"{len(option_underlying_watchlist)} option-underlying watchlist rows."
    )

    option_data_missing = []
    if include_options:
        option_data_missing = [
            item for item in list(dict.fromkeys(data_missing))
            if any(token in item.lower() for token in ("option", "opra", "bid/ask", "iv", "greeks", "fill", "quote"))
        ]

    return {
        "ok": True,
        "paper_trading_only": True,
        "summary": summary,
        "ranking_status": ranking_status,
        "option_discovery_status": option_discovery.get("status") if include_options and option_discovery else ("disabled" if not include_options else "not_available"),
        "options_final_eligibility": bool(option_discovery.get("options_final_eligibility")) if include_options and option_discovery else False,
        "paper_eligible": paper_eligible,
        "stock_watchlist": stock_watchlist,
        "option_research_only": option_research_only,
        "option_underlying_watchlist": option_underlying_watchlist,
        "blocked_but_interesting": blocked_but_interesting,
        "why_no_final_trades": why_no_final_trades,
        "data_missing": list(dict.fromkeys(data_missing)),
        "option_data_missing": option_data_missing,
        "system_issues": list(dict.fromkeys(system_issues)),
        "next_steps": list(dict.fromkeys(next_steps)),
        "warnings": [
            "Best Available Ideas is an explanatory ranking layer only.",
            "Only paper_eligible ideas may be logged as simulated paper trades by existing backend guardrails.",
        ],
    }
