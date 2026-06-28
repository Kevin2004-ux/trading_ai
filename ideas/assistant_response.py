from __future__ import annotations

from typing import Any

from discovery.source_models import summarize_discovery_result


TOP_LIST_LIMIT = 5


def _as_dict(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list:
    return value if isinstance(value, list) else []


def _safe_number(value: Any) -> float | int | None:
    try:
        if value is None or value == "":
            return None
        number = float(value)
    except (TypeError, ValueError):
        return None
    return int(number) if number.is_integer() else number


def _clean_text(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _extend_texts(rows: list[str], value: Any) -> None:
    if isinstance(value, str) and value.strip():
        rows.append(value.strip())
    elif isinstance(value, list):
        for item in value:
            if isinstance(item, str) and item.strip():
                rows.append(item.strip())


def _unique_texts(values: list[Any]) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for value in values:
        text = str(value).strip() if value is not None else ""
        if not text:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(text)
    return unique


def _sort_key(row: dict) -> tuple[float, float, float]:
    opportunity = _safe_number(row.get("opportunity_score"))
    engine = _safe_number(row.get("engine_score"))
    risk_reward = _safe_number(row.get("risk_reward"))
    return (
        float(opportunity) if opportunity is not None else -1.0,
        float(engine) if engine is not None else -1.0,
        float(risk_reward) if risk_reward is not None else -1.0,
    )


def _dedupe_rows(rows: list[dict], key_builder) -> list[dict]:
    seen: set[str] = set()
    unique: list[dict] = []
    for row in rows:
        key = key_builder(row)
        if key in seen:
            continue
        seen.add(key)
        unique.append(row)
    return unique


def _candidate_source(row: dict) -> dict:
    raw = _as_dict(row.get("raw_candidate"))
    return raw if raw else row


def _why_ranked(row: dict, *, blocked: bool = False) -> list[str]:
    source = _candidate_source(row)
    reasons: list[str] = []
    for key in ("why_selected", "why_this_profile_matched", "selection_reason", "thesis"):
        _extend_texts(reasons, source.get(key))

    relative_strength = _as_dict(source.get("relative_strength_context"))
    rs_label = _clean_text(relative_strength.get("relative_strength_label") or row.get("relative_strength"))
    if rs_label:
        reasons.append(f"Relative strength: {rs_label}.")

    technical = _as_dict(source.get("technical_confirmation_summary"))
    technical_status = _clean_text(technical.get("status"))
    if technical_status:
        reasons.append(f"Technical confirmation: {technical_status}.")

    catalyst = _as_dict(source.get("catalyst_context") or source.get("catalyst_summary"))
    catalyst_label = _clean_text(catalyst.get("summary") or catalyst.get("label") or catalyst.get("sentiment"))
    if catalyst_label:
        reasons.append(f"Catalyst context: {catalyst_label}.")

    if not reasons and not blocked:
        _extend_texts(reasons, row.get("reason"))
    if not reasons:
        score = _safe_number(row.get("idea_score") or row.get("score"))
        reasons.append(f"Ranked by deterministic opportunity score{f' {score}' if score is not None else ''}.")
    return _unique_texts(reasons)


def _constraint_confirmation(constraint: str) -> str | None:
    normalized = str(constraint or "").strip().lower()
    if not normalized:
        return None
    mapping = (
        (("minimum_relative_volume", "relative_volume", "volume"), "Relative volume must improve."),
        (("price_above_sma_20", "sma_20"), "Price must reclaim SMA 20."),
        (("price_above_sma_50", "sma_50"), "Price must reclaim SMA 50."),
        (("minimum_risk_reward", "risk_reward"), "Risk/reward must improve to the required threshold."),
        (("technical_confirmation_rejected", "technical_confirmation", "technical"), "Technical confirmation must improve."),
        (("trend",), "Trend conditions must improve."),
        (("portfolio",), "Portfolio risk must clear before actionability improves."),
        (("macro", "regime"), "Macro or market-regime risk must clear."),
    )
    for keys, message in mapping:
        if any(key in normalized for key in keys):
            return message
    return f"{constraint} must improve."


def _failed_constraints(row: dict) -> list[str]:
    source = _candidate_source(row)
    constraints: list[Any] = []
    constraints.extend(_as_list(row.get("failed_constraints")))
    constraints.extend(_as_list(source.get("failed_constraints")))
    constraints.extend(_as_list(_as_dict(source.get("constraint_results")).get("failed_constraints")))
    return _unique_texts(constraints)


def _key_risks(row: dict) -> list[str]:
    source = _candidate_source(row)
    risks: list[Any] = []
    _extend_texts(risks, source.get("key_risks"))
    _extend_texts(risks, source.get("risks"))
    _extend_texts(risks, source.get("invalidation"))
    _extend_texts(risks, row.get("rejection_reason"))
    _extend_texts(risks, source.get("rejection_reason"))
    data_quality = _as_dict(source.get("data_quality"))
    _extend_texts(risks, data_quality.get("warnings"))
    _extend_texts(risks, data_quality.get("errors"))
    return _unique_texts(risks)


def _normalize_stock(row: dict, status: str, rank: int) -> dict:
    setup = row.get("setup_type") or row.get("setup") or row.get("scan_profile")
    failed = _failed_constraints(row)
    opportunity_score = row.get("opportunity_score") if row.get("opportunity_score") is not None else row.get("idea_score")
    why_ranked = _as_list(row.get("why_ranked")) or _why_ranked(row, blocked=status == "blocked")
    key_risks = _as_list(row.get("key_risks")) or _key_risks(row)
    confirmation_needed = _as_list(row.get("confirmation_needed")) or [_constraint_confirmation(item) for item in failed]
    return {
        "ticker": str(row.get("ticker") or "").upper(),
        "asset_type": "stock",
        "status": status,
        "rank": rank,
        "opportunity_score": _safe_number(opportunity_score),
        "engine_score": _safe_number(row.get("score")),
        "setup": setup,
        "direction": row.get("direction"),
        "entry_price": _safe_number(row.get("entry_price")),
        "target_price": _safe_number(row.get("target_price")),
        "stop_loss": _safe_number(row.get("stop_loss")),
        "risk_reward": _safe_number(row.get("risk_reward")),
        "why_ranked": _unique_texts(why_ranked),
        "key_risks": _unique_texts(key_risks),
        "failed_constraints": failed,
        "confirmation_needed": _unique_texts(confirmation_needed),
        "data_quality": row.get("data_quality"),
    }


def _normalize_option(row: dict, status: str, rank: int) -> dict:
    opportunity_score = (
        row.get("option_opportunity_score")
        if row.get("option_opportunity_score") is not None
        else row.get("opportunity_score")
        if row.get("opportunity_score") is not None
        else row.get("idea_score")
    )
    return {
        "ticker": str(row.get("ticker") or "").upper(),
        "asset_type": "option",
        "status": status,
        "rank": rank,
        "opportunity_score": _safe_number(opportunity_score),
        "engine_score": _safe_number(row.get("score")),
        "strategy": row.get("strategy"),
        "option_contract": row.get("option_contract"),
        "option_type": row.get("option_type"),
        "strike": _safe_number(row.get("strike")),
        "expiration": row.get("expiration"),
        "days_to_expiration": _safe_number(row.get("days_to_expiration")),
        "bid": _safe_number(row.get("bid")),
        "ask": _safe_number(row.get("ask")),
        "mid": _safe_number(row.get("mid")),
        "spread_percent": _safe_number(row.get("spread_percent")),
        "open_interest": _safe_number(row.get("open_interest")),
        "volume": _safe_number(row.get("volume")),
        "implied_volatility": _safe_number(row.get("implied_volatility")),
        "iv_rank": _safe_number(row.get("iv_rank")),
        "delta": _safe_number(row.get("delta")),
        "breakeven_price": _safe_number(row.get("breakeven_price")),
        "why_ranked": _unique_texts(_as_list(row.get("why_ranked")) or _why_ranked(row, blocked=status == "blocked")),
        "key_risks": _unique_texts(_as_list(row.get("key_risks")) or _key_risks(row)),
        "missing_requirements": _unique_texts(_as_list(row.get("missing_requirements"))),
        "underlying_status": row.get("underlying_status"),
        "underlying_opportunity_score": _safe_number(row.get("underlying_opportunity_score")),
    }


def _normalize_option_underlying(row: dict, rank: int) -> dict:
    return {
        "ticker": str(row.get("ticker") or "").upper(),
        "asset_type": "option_underlying",
        "status": "watchlist",
        "rank": rank,
        "option_bias": row.get("option_bias"),
        "underlying_opportunity_score": _safe_number(row.get("underlying_opportunity_score")),
        "underlying_status": row.get("underlying_status"),
        "why_watch": _unique_texts(_as_list(row.get("why_watch"))),
        "required_before_contract_ranking": _unique_texts(_as_list(row.get("required_before_contract_ranking"))),
    }


def _stock_status(row: dict) -> str:
    bucket = str(row.get("bucket") or "").lower()
    status = str(row.get("recommendation_status") or "").lower()
    if bucket == "paper_eligible" or status == "paper_eligible" or status == "recommendable":
        return "paper_eligible"
    if bucket == "watchlist" or status == "watchlist":
        return "watchlist"
    return "blocked"


def _option_status(row: dict) -> str:
    bucket = str(row.get("bucket") or "").lower()
    status = str(row.get("recommendation_status") or "").lower()
    if bucket == "paper_eligible" or status == "paper_eligible" or status == "recommendable":
        return "paper_eligible"
    if bucket == "research_only" or status == "research_only" or status == "watchlist":
        return "research_only"
    return "blocked"


def _renumber(rows: list[dict]) -> list[dict]:
    for index, row in enumerate(rows, start=1):
        row["rank"] = index
    return rows


def _empty_research_fields() -> dict:
    return {
        "research_status": "not_requested",
        "research_summary": None,
        "current_catalysts": [],
        "current_risks": [],
        "research_uncertainties": [],
        "research_source_ids": [],
    }


def _research_lookup(research: dict | None) -> dict[str, dict]:
    payload = _as_dict(research)
    return {
        str(dossier.get("ticker") or "").upper(): dossier
        for dossier in _as_list(payload.get("dossiers"))
        if isinstance(dossier, dict) and dossier.get("ticker")
    }


def _apply_research_context(rows: list[dict], research: dict | None) -> list[dict]:
    lookup = _research_lookup(research)
    requested = bool(_as_dict(research).get("scopes_requested"))
    enriched: list[dict] = []
    for row in rows:
        updated = {**row, **_empty_research_fields()}
        ticker = str(row.get("ticker") or "").upper()
        dossier = lookup.get(ticker)
        if dossier:
            updated["research_status"] = dossier.get("status") or "unavailable"
            updated["research_summary"] = dossier.get("summary")
            updated["current_catalysts"] = list(_as_list(dossier.get("positive_catalysts")))[:3]
            updated["current_risks"] = list(_as_list(dossier.get("negative_catalysts")))[:3]
            updated["research_uncertainties"] = list(_as_list(dossier.get("uncertainties")))[:3]
            updated["research_source_ids"] = list(_as_list(dossier.get("source_ids")))[:5]
        elif requested:
            updated["research_status"] = "unavailable"
        enriched.append(updated)
    return enriched


def _extract_market_regime(trading_result: dict) -> Any:
    root = _as_dict(trading_result)
    trade_hunt = _as_dict(root.get("trade_hunt"))
    for source in (root, trade_hunt, _as_dict(root.get("summary")), _as_dict(trade_hunt.get("summary"))):
        for key in ("market_regime", "market_regime_summary", "regime"):
            value = source.get(key)
            if value not in (None, "", [], {}):
                return value
    return None


def _extract_data_freshness(trading_result: dict) -> Any:
    root = _as_dict(trading_result)
    trade_hunt = _as_dict(root.get("trade_hunt"))
    scan_result = _as_dict(root.get("scan_result") or trade_hunt.get("scan_result"))
    data_quality = _as_dict(scan_result.get("data_quality_summary"))
    for key in ("freshness_label", "data_freshness", "market_data_freshness", "worst_freshness_label"):
        value = data_quality.get(key) or scan_result.get(key) or root.get(key)
        if value not in (None, "", [], {}):
            return value
    return None


def _provider_status(best_ideas: dict) -> str:
    ranking_status = best_ideas.get("ranking_status")
    issues = list(_as_list(best_ideas.get("system_issues"))) + list(_as_list(best_ideas.get("data_missing")))
    issue_text = " ".join(str(item).lower() for item in issues)
    if ranking_status == "unavailable":
        return "unavailable" if any(token in issue_text for token in ("provider", "ibkr", "tws", "market data", "historical bars", "quote")) else "unknown"
    if issues:
        return "degraded"
    if ranking_status == "available":
        return "available"
    return "unknown"


def _partial_results(best_ideas: dict, trading_result: dict) -> bool:
    root = _as_dict(trading_result)
    summary = _as_dict(root.get("summary") or _as_dict(root.get("trade_hunt")).get("summary"))
    value = root.get("partial_results", summary.get("partial_results"))
    if isinstance(value, bool):
        return value
    return bool(best_ideas.get("system_issues") or best_ideas.get("data_missing")) and best_ideas.get("ranking_status") == "available"


def _discovery_summary(trading_result: dict) -> dict:
    root = _as_dict(trading_result)
    trade_hunt = _as_dict(root.get("trade_hunt"))
    summary = _as_dict(root.get("discovery_summary") or trade_hunt.get("discovery_summary"))
    if summary:
        return summary
    return summarize_discovery_result(_as_dict(root.get("discovery_result") or trade_hunt.get("discovery_result")))


def _scan_summary(trading_result: dict, run_id: str | None, include_options: bool, partial_results: bool) -> dict:
    root = _as_dict(trading_result)
    trade_hunt = _as_dict(root.get("trade_hunt"))
    scan_result = _as_dict(root.get("scan_result") or trade_hunt.get("scan_result"))
    summary = _as_dict(root.get("summary") or trade_hunt.get("summary"))
    universe_result = _as_dict(root.get("universe_result") or trade_hunt.get("universe_result"))
    execution = _as_dict(root.get("scan_execution_summary") or scan_result.get("scan_execution_summary") or trade_hunt.get("scan_execution_summary"))
    profiles = summary.get("profiles_run") or scan_result.get("profiles_run") or execution.get("profiles_run") or []
    tickers_scanned = (
        summary.get("tickers_scanned")
        or summary.get("total_scanned")
        or scan_result.get("total_scanned")
        or execution.get("completed_ticker_count")
        or universe_result.get("total_tickers")
    )
    return {
        "run_id": run_id or root.get("run_id") or root.get("pipeline_run_id") or summary.get("run_id"),
        "universe": root.get("universe") or summary.get("universe") or universe_result.get("universe"),
        "tickers_scanned": int(tickers_scanned) if isinstance(tickers_scanned, int | float) else None,
        "profiles_run": profiles if isinstance(profiles, list) else [],
        "include_options": bool(include_options),
        "options_final_eligibility": bool(_as_dict(root.get("option_discovery")).get("options_final_eligibility")),
        "partial_results": partial_results,
    }


def _requested_instrument(value: str) -> str:
    normalized = str(value or "auto").strip().lower()
    if normalized in {"stocks", "stock", "equities", "equity"}:
        return "stocks"
    if normalized in {"options", "option"}:
        return "options"
    if normalized in {"both", "all"}:
        return "both"
    return "auto"


def _include_options(best_ideas: dict, trading_result: dict, requested_instrument: str) -> bool:
    if requested_instrument == "stocks":
        return False
    if requested_instrument in {"options", "both"}:
        return True
    root = _as_dict(trading_result)
    if isinstance(root.get("include_options"), bool):
        return root["include_options"]
    return bool(
        best_ideas.get("option_research_only")
        or best_ideas.get("option_underlying_watchlist")
        or any(str(item.get("asset_type", "")).lower() == "option" for item in _as_list(best_ideas.get("blocked_but_interesting")))
    )


def build_assistant_trade_response(
    best_ideas: dict,
    trading_result: dict | None = None,
    requested_instrument: str = "auto",
    run_id: str | None = None,
    research: dict | None = None,
) -> dict:
    best_ideas = _as_dict(best_ideas)
    trading_result = _as_dict(trading_result)
    requested = _requested_instrument(requested_instrument)
    include_options = _include_options(best_ideas, trading_result, requested)
    ranking_status = str(best_ideas.get("ranking_status") or "no_qualifying_ideas")

    stock_rows: list[dict] = []
    option_rows: list[dict] = []
    option_underlying_rows: list[dict] = []
    if ranking_status != "unavailable":
        for source_row in _as_list(best_ideas.get("paper_eligible")):
            row = _as_dict(source_row)
            if str(row.get("asset_type", "stock")).lower() == "option":
                option_rows.append(_normalize_option(row, "paper_eligible", 0))
            else:
                stock_rows.append(_normalize_stock(row, "paper_eligible", 0))
        for source_row in _as_list(best_ideas.get("stock_watchlist")):
            row = _as_dict(source_row)
            stock_rows.append(_normalize_stock(row, "watchlist", 0))
        for source_row in _as_list(best_ideas.get("option_research_only")):
            row = _as_dict(source_row)
            option_rows.append(_normalize_option(row, "research_only", 0))
        for source_row in _as_list(best_ideas.get("blocked_but_interesting")):
            row = _as_dict(source_row)
            if str(row.get("asset_type", "stock")).lower() == "option":
                option_rows.append(_normalize_option(row, "blocked", 0))
            else:
                stock_rows.append(_normalize_stock(row, "blocked", 0))
        for source_row in _as_list(best_ideas.get("option_underlying_watchlist")):
            row = _as_dict(source_row)
            option_underlying_rows.append(_normalize_option_underlying(row, 0))

    stock_rows = _dedupe_rows(
        sorted(stock_rows, key=_sort_key, reverse=True),
        lambda row: f"{row.get('ticker')}:{row.get('setup')}:{row.get('status')}",
    )[:TOP_LIST_LIMIT]
    option_rows = _dedupe_rows(
        sorted(option_rows, key=_sort_key, reverse=True),
        lambda row: row.get("option_contract") or f"{row.get('ticker')}:{row.get('strategy')}:{row.get('expiration')}:{row.get('status')}",
    )[:TOP_LIST_LIMIT]
    stock_rows = _renumber(stock_rows)
    option_rows = _renumber(option_rows)
    option_underlying_rows = _renumber(
        _dedupe_rows(
            sorted(option_underlying_rows, key=lambda row: float(row.get("underlying_opportunity_score") or -1.0), reverse=True),
            lambda row: str(row.get("ticker")),
        )[:TOP_LIST_LIMIT]
    )
    stock_rows = _apply_research_context(stock_rows, research)
    option_rows = _apply_research_context(option_rows, research)
    option_underlying_rows = _apply_research_context(option_underlying_rows, research)

    paper_eligible = [row for row in stock_rows + option_rows if row.get("status") == "paper_eligible"]
    research_only = [row for row in stock_rows + option_rows if row.get("status") in {"watchlist", "research_only"}]
    blocked = [row for row in stock_rows + option_rows if row.get("status") == "blocked"]
    partial = _partial_results(best_ideas, trading_result)
    provider_status = _provider_status(best_ideas)
    discovery = _discovery_summary(trading_result)
    market_message = None
    if ranking_status == "unavailable":
        market_message = "Ranking unavailable because usable market data was not returned."
    elif provider_status == "degraded":
        market_message = "Ranking is available, but some provider/data issues remain."

    research_payload = _as_dict(research)
    return {
        "ok": True,
        "response_type": "trade_ideas",
        "paper_trading_only": True,
        "ranking_status": ranking_status,
        "research_status": research_payload.get("status", "not_requested") if research_payload else "not_requested",
        "research_sources": list(_as_list(research_payload.get("sources"))) if research_payload else [],
        "research_warnings": list(_as_list(research_payload.get("warnings"))) if research_payload else [],
        "requested_instrument": requested,
        "market_state": {
            "provider_status": provider_status,
            "market_regime": _extract_market_regime(trading_result),
            "data_freshness": _extract_data_freshness(trading_result),
            "partial_results": partial,
            "discovery_used": bool(discovery.get("discovery_used")),
            "discovered_count": discovery.get("discovered_count", 0),
            "sources_used": list(_as_list(discovery.get("sources_used"))),
            "discovery_summary": discovery,
            "message": market_message,
        },
        "top_stocks": stock_rows if requested != "options" else [],
        "top_options": option_rows if include_options and requested != "stocks" else [],
        "option_underlying_watchlist": option_underlying_rows if include_options and requested != "stocks" else [],
        "option_discovery_status": best_ideas.get("option_discovery_status", "disabled" if not include_options else "not_available"),
        "option_data_missing": list(_as_list(best_ideas.get("option_data_missing"))),
        "paper_eligible": paper_eligible,
        "research_only": research_only,
        "blocked": blocked,
        "why_no_final_trades": list(_as_list(best_ideas.get("why_no_final_trades"))),
        "data_missing": list(_as_list(best_ideas.get("data_missing"))),
        "system_issues": list(_as_list(best_ideas.get("system_issues"))),
        "next_steps": list(_as_list(best_ideas.get("next_steps"))),
        "scan_summary": _scan_summary(trading_result, run_id, include_options, partial),
        "refinement": {
            "used": False,
            "passes_executed": 1,
            "stop_reason": "",
            "changes": [],
            "warnings": [],
        },
    }
