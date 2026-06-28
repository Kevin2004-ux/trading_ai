from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any
import math
import re

from engine.constraint_engine import evaluate_option_constraints
from ideas.data_failures import has_trade_prices, is_data_failure_candidate, normalized_text
from ideas.option_opportunity_ranker import score_option_opportunity
from options.options_risk import evaluate_option_trade_risk
from options.strategy_builder import (
    BEARISH_OPTION_STRATEGY_TYPES,
    BULLISH_OPTION_STRATEGY_TYPES,
    NEUTRAL_OPTION_STRATEGY_TYPES,
    SUPPORTED_OPTION_STRATEGY_TYPES,
    build_option_strategy_candidates,
)
from realtime.options_chain import calculate_option_metrics, get_options_chain, normalize_options_chain


OPTION_DISCOVERY_VERSION = "option_discovery_v1"
TICKER_PATTERN = re.compile(r"^[A-Z]{1,5}(?:[.-][A-Z])?$")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _as_dict(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list:
    return value if isinstance(value, list) else []


def _safe_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric if math.isfinite(numeric) else None


def _safe_int(value: Any) -> int | None:
    numeric = _safe_float(value)
    return int(numeric) if numeric is not None else None


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


def _empty_response(
    *,
    requested: bool,
    status: str,
    provider_status: str = "unknown",
    options_final_eligibility: bool = False,
    warnings: list[str] | None = None,
    errors: list[str] | None = None,
    missing_requirements: list[str] | None = None,
) -> dict:
    return {
        "ok": status not in {"failed"},
        "discovery_version": OPTION_DISCOVERY_VERSION,
        "timestamp": _now_iso(),
        "status": status,
        "paper_trading_only": True,
        "brokerage_execution_enabled": False,
        "requested": bool(requested),
        "provider_status": provider_status,
        "options_final_eligibility": bool(options_final_eligibility),
        "underlyings_considered": [],
        "underlying_shortlist": [],
        "contracts_evaluated": 0,
        "strategies_evaluated": 0,
        "paper_eligible_contracts": [],
        "research_only_contracts": [],
        "blocked_contracts": [],
        "underlying_watchlist": [],
        "missing_requirements": list(missing_requirements or []),
        "warnings": list(warnings or []),
        "errors": list(errors or []),
    }


def empty_option_discovery_response(requested: bool = False, reason: str | None = None) -> dict:
    warnings = [reason] if reason else []
    return _empty_response(
        requested=requested,
        status="disabled" if not requested else "unavailable",
        provider_status="unknown",
        warnings=warnings,
        missing_requirements=[] if not requested else ["option_discovery_not_available"],
    )


def _valid_ticker(value: Any) -> str:
    ticker = str(value or "").strip().upper()
    return ticker if TICKER_PATTERN.fullmatch(ticker) else ""


def _candidate_source(candidate: dict) -> dict:
    raw = _as_dict(candidate.get("raw_candidate"))
    merged = deepcopy(raw if raw else candidate)
    for key, value in candidate.items():
        if key == "raw_candidate":
            continue
        merged.setdefault(key, value)
    return merged


def _field(candidate: dict, key: str) -> Any:
    if candidate.get(key) is not None:
        return candidate.get(key)
    for nested_key in ("technical_snapshot", "technical", "metrics", "data", "raw_candidate"):
        nested = candidate.get(nested_key)
        if isinstance(nested, dict) and nested.get(key) is not None:
            return nested.get(key)
    return None


def _underlying_price(candidate: dict) -> float | None:
    return (
        _safe_float(_field(candidate, "current_price"))
        or _safe_float(_field(candidate, "entry_price"))
        or _safe_float(_field(candidate, "underlying_price"))
    )


def _underlying_status(candidate: dict) -> str:
    status = str(candidate.get("status") or candidate.get("recommendation_status") or candidate.get("bucket") or "").lower()
    if status in {"recommendable", "paper_eligible"}:
        return "paper_eligible"
    if status == "watchlist":
        return "watchlist"
    return "blocked"


def _option_bias(candidate: dict) -> str:
    value = str(candidate.get("option_bias") or candidate.get("bias") or candidate.get("direction") or "").lower()
    if value in {"long", "bullish", "up", "upside"}:
        return "bullish"
    if value in {"short", "bearish", "down", "downside"}:
        return "bearish"

    technical = _as_dict(candidate.get("technical_confirmation_summary"))
    technical_status = str(technical.get("bias") or technical.get("direction") or technical.get("status") or "").lower()
    if technical_status in {"bullish", "long", "confirmed", "passed", "pass"}:
        return "bullish"
    if technical_status in {"bearish", "short"}:
        return "bearish"
    return "neutral"


def _score_for_sort(candidate: dict) -> tuple[float, float, float]:
    return (
        _safe_float(candidate.get("opportunity_score"))
        or _safe_float(candidate.get("underlying_opportunity_score"))
        or _safe_float(candidate.get("idea_score"))
        or -1.0,
        _safe_float(candidate.get("score")) or _safe_float(candidate.get("underlying_engine_score")) or -1.0,
        _safe_float(candidate.get("risk_reward")) or -1.0,
    )


def _underlying_reason(candidate: dict) -> list[str]:
    reasons: list[Any] = []
    for key in ("why_ranked", "why_selected", "why_this_profile_matched", "selection_reason", "reason", "thesis"):
        value = candidate.get(key)
        if isinstance(value, list):
            reasons.extend(value)
        elif value:
            reasons.append(value)
    if not reasons:
        score = _safe_float(candidate.get("opportunity_score") or candidate.get("idea_score") or candidate.get("score"))
        reasons.append(f"Selected by deterministic underlying rank{f' {round(score, 2)}' if score is not None else ''}.")
    return _unique_texts(reasons)[:5]


def _underlying_blockers(candidate: dict) -> list[str]:
    blockers: list[Any] = []
    blockers.extend(_as_list(candidate.get("failed_constraints")))
    blockers.extend(_as_list(_as_dict(candidate.get("constraint_results")).get("failed_constraints")))
    if candidate.get("rejection_reason"):
        blockers.append(candidate.get("rejection_reason"))
    return _unique_texts(blockers)


def _candidate_to_underlying_row(candidate: dict, index: int) -> dict:
    source = _candidate_source(candidate)
    ticker = _valid_ticker(source.get("ticker") or candidate.get("ticker"))
    price = _underlying_price(source)
    return {
        "ticker": ticker,
        "direction": str(source.get("direction") or candidate.get("direction") or "long").lower(),
        "underlying_status": _underlying_status(candidate),
        "underlying_opportunity_score": _safe_float(candidate.get("opportunity_score") or source.get("opportunity_score") or candidate.get("idea_score") or source.get("idea_score")),
        "underlying_engine_score": _safe_float(candidate.get("score") or source.get("score")),
        "setup": candidate.get("setup") or candidate.get("setup_type") or source.get("setup_type") or source.get("scan_profile"),
        "current_price": price,
        "entry_price": _safe_float(_field(source, "entry_price")),
        "target_price": _safe_float(_field(source, "target_price")),
        "stop_loss": _safe_float(_field(source, "stop_loss")),
        "risk_reward": _safe_float(_field(source, "risk_reward")),
        "option_bias": _option_bias(source),
        "why_selected_for_option_research": _underlying_reason(candidate),
        "underlying_blockers": _underlying_blockers(source),
        "source_order": index,
        "raw_underlying_candidate": deepcopy(source),
    }


def _build_underlying_shortlist(
    stock_candidates: list[dict],
    explicit_tickers: list[str] | None,
    max_underlyings: int,
) -> tuple[list[dict], list[dict], list[str], list[str]]:
    considered: list[dict] = []
    rejected: list[dict] = []
    warnings: list[str] = []
    missing: list[str] = []
    explicit = [_valid_ticker(item) for item in explicit_tickers or []]
    explicit = [item for item in explicit if item]
    explicit_set = set(explicit)

    for index, candidate in enumerate(stock_candidates or []):
        if not isinstance(candidate, dict):
            continue
        source = _candidate_source(candidate)
        ticker = _valid_ticker(source.get("ticker") or candidate.get("ticker"))
        if not ticker:
            rejected.append({"reason": "malformed_ticker", "candidate": deepcopy(candidate)})
            continue
        if explicit_set and ticker not in explicit_set:
            continue
        if is_data_failure_candidate(source) or is_data_failure_candidate(candidate):
            rejected.append({"ticker": ticker, "reason": "data_failure", "candidate": deepcopy(candidate)})
            continue
        if not has_trade_prices(source) or _underlying_price(source) is None:
            rejected.append({"ticker": ticker, "reason": "missing_underlying_price", "candidate": deepcopy(candidate)})
            missing.append("Usable underlying price is required before option contracts can be ranked.")
            continue
        considered.append(_candidate_to_underlying_row(candidate, index))

    if explicit and not considered:
        missing.append("Explicit ticker option review requires a usable underlying price from deterministic stock discovery.")
    if not considered and not explicit:
        missing.append("No legitimate stock candidates with usable market data were available for option discovery.")

    unique_by_ticker: dict[str, dict] = {}
    for row in considered:
        ticker = row["ticker"]
        if ticker not in unique_by_ticker:
            unique_by_ticker[ticker] = row
            continue
        existing = unique_by_ticker[ticker]
        current_key = (*_score_for_sort(row), -int(row.get("source_order") or 0))
        existing_key = (*_score_for_sort(existing), -int(existing.get("source_order") or 0))
        if current_key > existing_key:
            unique_by_ticker[ticker] = row

    sorted_rows = sorted(
        unique_by_ticker.values(),
        key=lambda row: (*_score_for_sort(row), -int(row.get("source_order") or 0)),
        reverse=True,
    )
    max_count = max(1, int(max_underlyings or 1))
    return sorted_rows[:max_count], rejected, _unique_texts(missing), _unique_texts(warnings)


def _allowed_strategy_types(option_preferences: dict) -> tuple[set[str], list[str]]:
    requested = {str(item).strip().lower() for item in _as_list(option_preferences.get("allowed_strategy_types")) if str(item).strip()}
    if not requested:
        return set(SUPPORTED_OPTION_STRATEGY_TYPES), []
    supported = set(SUPPORTED_OPTION_STRATEGY_TYPES)
    unknown = sorted(requested - supported)
    return requested.intersection(supported), [f"Unsupported option strategy types were ignored: {', '.join(unknown)}."] if unknown else []


def _strategy_types_for_bias(bias: str, allowed: set[str]) -> set[str]:
    if bias == "bullish":
        compatible = set(BULLISH_OPTION_STRATEGY_TYPES)
    elif bias == "bearish":
        compatible = set(BEARISH_OPTION_STRATEGY_TYPES)
    else:
        compatible = set(NEUTRAL_OPTION_STRATEGY_TYPES)
    return compatible.intersection(allowed)


def _exact_option_types_for_bias(bias: str, compatible_strategies: set[str]) -> set[str]:
    if bias == "bullish" and "long_call" in compatible_strategies:
        return {"call"}
    if bias == "bearish" and "long_put" in compatible_strategies:
        return {"put"}
    return set()


def _option_type_for_strategy(strategy_type: str) -> str | None:
    if "call" in strategy_type or strategy_type == "covered_call_research":
        return "call"
    if "put" in strategy_type or strategy_type == "cash_secured_put_research":
        return "put"
    return None


def _simple_strategy_for_option_type(option_type: str, compatible_strategies: set[str]) -> str | None:
    if option_type == "call" and "long_call" in compatible_strategies:
        return "long_call"
    if option_type == "put" and "long_put" in compatible_strategies:
        return "long_put"
    for strategy_type in sorted(compatible_strategies):
        if _option_type_for_strategy(strategy_type) == option_type:
            return strategy_type
    return None


def _option_contract_id(option: dict) -> str:
    return str(option.get("option_contract") or option.get("ticker") or "").upper()


def _risk_reward_for_option(option: dict, underlying: dict, metrics: dict) -> float | None:
    mid = _safe_float(metrics.get("mid") or option.get("mid"))
    strike = _safe_float(option.get("strike"))
    target = _safe_float(underlying.get("target_price"))
    stop = _safe_float(underlying.get("stop_loss"))
    option_type = str(option.get("option_type") or "").lower()
    if mid in (None, 0) or strike is None or target is None or stop is None:
        return None
    if option_type == "call":
        target_value = max(target - strike, 0.0)
        stop_value = max(stop - strike, 0.0)
    elif option_type == "put":
        target_value = max(strike - target, 0.0)
        stop_value = max(strike - stop, 0.0)
    else:
        return None
    expected_profit = target_value - mid
    estimated_loss = max(mid - stop_value, 0.0)
    if estimated_loss <= 0:
        return None
    return expected_profit / estimated_loss


def _constraint_underlying_result(underlying: dict) -> dict:
    status = str(underlying.get("underlying_status") or "").lower()
    return {
        "passed": status == "paper_eligible",
        "recommendation_status": "recommendable" if status == "paper_eligible" else status,
        "score": _safe_float(underlying.get("underlying_engine_score")),
    }


def _evaluate_contract(
    option: dict,
    underlying: dict,
    strategy_type: str,
    option_preferences: dict,
    options_final_eligibility: bool,
    runtime_context: dict,
) -> dict:
    current_price = _safe_float(underlying.get("current_price")) or 0.0
    target = _safe_float(underlying.get("target_price"))
    metrics = calculate_option_metrics(option, underlying_price=current_price, expected_target_price=target)
    candidate = {
        **option,
        **metrics,
        "asset_type": "option",
        "ticker": underlying.get("ticker"),
        "underlying_ticker": underlying.get("ticker"),
        "underlying_price": current_price,
        "underlying_entry_price": underlying.get("entry_price"),
        "underlying_target_price": underlying.get("target_price"),
        "underlying_stop_loss": underlying.get("stop_loss"),
        "expected_target_price": target,
        "strategy": strategy_type,
        "direction": "long",
        "underlying_status": underlying.get("underlying_status"),
        "underlying_opportunity_score": underlying.get("underlying_opportunity_score"),
        "underlying_engine_score": underlying.get("underlying_engine_score"),
        "underlying_candidate": deepcopy(underlying.get("raw_underlying_candidate") or underlying),
    }
    risk_reward = _risk_reward_for_option(candidate, underlying, metrics)
    candidate["risk_reward"] = risk_reward
    risk = evaluate_option_trade_risk(candidate)
    candidate["iv_context"] = risk.get("iv_context")
    candidate["greeks_monitoring"] = risk.get("greeks")
    candidate["option_trade_risk"] = risk
    candidate["options_research_status"] = risk.get("options_research_status", "blocked")
    constraints = evaluate_option_constraints(candidate, underlying_result=_constraint_underlying_result(underlying))
    candidate["constraint_results"] = constraints.get("constraint_results", {})
    candidate["failed_constraints"] = list(constraints.get("failed_constraints", []))
    candidate["deterministic_recommendation_status"] = constraints.get("recommendation_status")
    candidate["score"] = constraints.get("score")
    candidate["passed"] = bool(constraints.get("passed"))
    candidate["rejection_reason"] = constraints.get("rejection_reason")

    max_premium = _safe_float(option_preferences.get("max_option_premium") or option_preferences.get("max_premium") or option_preferences.get("max_debit"))
    quoted_price = _safe_float(candidate.get("mid") or candidate.get("ask") or candidate.get("last") or candidate.get("close"))
    estimated_contract_premium = round(quoted_price * 100.0, 2) if quoted_price is not None else None
    candidate["max_option_premium"] = max_premium
    candidate["estimated_contract_premium"] = estimated_contract_premium
    if max_premium is not None and estimated_contract_premium is not None and estimated_contract_premium > max_premium:
        candidate["failed_constraints"] = _unique_texts(candidate.get("failed_constraints", []) + ["max_option_premium"])
        premium_reason = f"Estimated contract premium ${estimated_contract_premium:.2f} exceeds requested max premium ${max_premium:.2f}."
        candidate["rejection_reason"] = "; ".join(_unique_texts([candidate.get("rejection_reason"), premium_reason]))
        candidate["passed"] = False

    if risk.get("approved") and constraints.get("recommendation_status") == "recommendable" and bool(candidate.get("passed")) and options_final_eligibility:
        actionability = "paper_eligible"
        candidate["recommendation_status"] = "paper_eligible"
    elif risk.get("status") == "blocked" or not bool(candidate.get("passed")):
        actionability = "blocked"
        candidate["recommendation_status"] = "blocked"
    else:
        actionability = "research_only"
        candidate["recommendation_status"] = "research_only"

    missing = list(_as_list(candidate.get("missing_requirements")))
    if not options_final_eligibility:
        missing.append("options_runtime_readiness")
        candidate.setdefault("warnings", []).append("Final option eligibility is false until options runtime readiness and deterministic gates pass.")
    if runtime_context.get("safe_to_run_options") is False:
        candidate.setdefault("warnings", []).append("Runtime reports options are not safe for final paper eligibility.")
    if "max_option_premium" in candidate.get("failed_constraints", []):
        missing.append("requested_option_premium_budget")
    candidate["actionability_status"] = actionability
    candidate["missing_requirements"] = _unique_texts(missing)

    opportunity = score_option_opportunity(
        candidate,
        underlying_candidate=underlying,
        config={
            **_as_dict(option_preferences),
            "option_preferences": option_preferences,
        },
    )
    candidate.update(
        {
            "option_opportunity_score": opportunity.get("opportunity_score"),
            "option_opportunity_score_version": opportunity.get("score_version"),
            "option_opportunity_components": opportunity.get("components", {}),
            "option_data_confidence": opportunity.get("data_confidence"),
            "why_ranked": opportunity.get("why_ranked", []),
            "key_risks": opportunity.get("key_risks", []),
            "missing_requirements": _unique_texts(candidate.get("missing_requirements", []) + opportunity.get("missing_requirements", [])),
            "qualification_gaps": opportunity.get("qualification_gaps", []),
            "rankable": opportunity.get("rankable"),
        }
    )
    return candidate


def _watchlist_row(underlying: dict, requirements: list[str], why_watch: list[str] | None = None) -> dict:
    return {
        "ticker": underlying.get("ticker"),
        "option_bias": underlying.get("option_bias"),
        "underlying_opportunity_score": underlying.get("underlying_opportunity_score"),
        "underlying_status": underlying.get("underlying_status"),
        "why_watch": _unique_texts(why_watch or underlying.get("why_selected_for_option_research", [])),
        "required_before_contract_ranking": _unique_texts(requirements),
        "paper_trading_only": True,
    }


def _provider_issue_messages(result: dict) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    missing: list[str] = []
    error = result.get("error") if isinstance(result, dict) else None
    if error:
        errors.append(str(error))
    text = normalized_text(result)
    if "opra" in text or "permission" in text or "subscription" in text:
        missing.append("OPRA/options quote permissions may be missing.")
    if "quote" in text or "bid/ask" in text:
        missing.append("Option bid/ask quotes are unavailable.")
    if "chain" in text:
        missing.append("Option chain data is unavailable.")
    return _unique_texts(missing), _unique_texts(errors)


def _sort_contracts(rows: list[dict]) -> list[dict]:
    return sorted(
        rows,
        key=lambda row: (
            _safe_float(row.get("option_opportunity_score")) if row.get("option_opportunity_score") is not None else -1.0,
            _safe_float(row.get("score")) or -1.0,
            _safe_float(row.get("risk_reward")) or -1.0,
            -(_safe_float(row.get("spread_percent")) or 999.0),
            str(row.get("option_contract") or ""),
        ),
        reverse=True,
    )


def discover_option_ideas(
    stock_candidates: list[dict],
    explicit_tickers: list[str] | None = None,
    option_preferences: dict | None = None,
    runtime_context: dict | None = None,
    max_underlyings: int = 5,
    max_contracts_per_ticker: int = 3,
) -> dict:
    option_preferences = _as_dict(option_preferences)
    runtime_context = _as_dict(runtime_context)
    requested = bool(runtime_context.get("requested", True))
    if not requested:
        return empty_option_discovery_response(requested=False, reason="Option discovery was not requested.")

    options_final_eligibility = bool(runtime_context.get("safe_to_run_options") or runtime_context.get("options_final_eligibility"))
    response = _empty_response(
        requested=True,
        status="unavailable",
        provider_status="unknown",
        options_final_eligibility=options_final_eligibility,
    )
    allowed_strategies, strategy_warnings = _allowed_strategy_types(option_preferences)
    response["warnings"].extend(strategy_warnings)

    shortlist, rejected_underlyings, missing, shortlist_warnings = _build_underlying_shortlist(
        stock_candidates,
        explicit_tickers=explicit_tickers,
        max_underlyings=max_underlyings,
    )
    response["underlyings_considered"] = shortlist + rejected_underlyings
    response["underlying_shortlist"] = shortlist
    response["missing_requirements"].extend(missing)
    response["warnings"].extend(shortlist_warnings)

    if not shortlist:
        response["status"] = "unavailable"
        response["provider_status"] = "unknown"
        response["missing_requirements"] = _unique_texts(response["missing_requirements"])
        return response

    min_dte = _safe_int(option_preferences.get("min_dte")) or 14
    max_dte = _safe_int(option_preferences.get("max_dte")) or 56
    max_contracts = max(1, int(max_contracts_per_ticker or 1))
    provider_success = 0
    provider_failures = 0
    metadata_only = 0

    for underlying in shortlist:
        ticker = str(underlying.get("ticker") or "").upper()
        compatible_strategies = _strategy_types_for_bias(str(underlying.get("option_bias") or "neutral").lower(), allowed_strategies)
        if not compatible_strategies:
            response["warnings"].append(f"No supported option strategies matched {ticker}'s {underlying.get('option_bias')} bias.")
            response["underlying_watchlist"].append(
                _watchlist_row(underlying, ["supported_strategy_type"], ["No supported option strategy matched this underlying bias."])
            )
            continue

        chain_result = get_options_chain(ticker, min_days_to_expiration=min_dte, max_days_to_expiration=max_dte)
        if not isinstance(chain_result, dict) or not chain_result.get("ok"):
            provider_failures += 1
            missing_rows, errors = _provider_issue_messages(chain_result if isinstance(chain_result, dict) else {"error": "Options provider returned malformed response."})
            response["missing_requirements"].extend(missing_rows or ["Option chain/quote data is unavailable."])
            response["errors"].extend(errors or ["Options provider returned no usable chain data."])
            continue

        provider_success += 1
        raw_contracts = _as_list(_as_dict(chain_result.get("data")).get("contracts"))
        normalized_chain = normalize_options_chain(raw_contracts)
        if not normalized_chain:
            metadata_only += 1
            response["underlying_watchlist"].append(_watchlist_row(underlying, ["option_chain", "bid/ask", "IV", "Greeks", "liquidity", "fill quality"]))
            continue

        strategy_build = build_option_strategy_candidates(
            ticker,
            {
                **deepcopy(underlying.get("raw_underlying_candidate") or {}),
                "ticker": ticker,
                "current_price": underlying.get("current_price"),
                "direction": underlying.get("direction"),
                "option_bias": underlying.get("option_bias"),
            },
            normalized_chain,
        )
        strategies = [
            item for item in _as_list(strategy_build.get("strategies"))
            if str(item.get("strategy_type") or "").lower() in compatible_strategies
        ]
        response["strategies_evaluated"] += len(strategies)

        compatible_option_types = _exact_option_types_for_bias(str(underlying.get("option_bias") or "neutral").lower(), compatible_strategies)
        evaluated_for_ticker: list[dict] = []
        for option in normalized_chain:
            option_type = str(option.get("option_type") or "").lower()
            if option_type not in compatible_option_types:
                continue
            strategy_type = _simple_strategy_for_option_type(option_type, compatible_strategies)
            if strategy_type is None:
                continue
            response["contracts_evaluated"] += 1
            evaluated = _evaluate_contract(
                option,
                underlying,
                strategy_type,
                option_preferences,
                options_final_eligibility,
                runtime_context,
            )
            if not evaluated.get("rankable"):
                metadata_only += 1
                continue
            evaluated_for_ticker.append(evaluated)

        if not evaluated_for_ticker:
            response["underlying_watchlist"].append(
                _watchlist_row(
                    underlying,
                    ["bid/ask", "IV", "Greeks", "liquidity", "OPRA permissions", "fill quality"],
                    ["Option metadata exists, but no exact contracts had enough quote data for ranking."],
                )
            )
            continue

        ranked_for_ticker = _sort_contracts(evaluated_for_ticker)[:max_contracts]
        for contract in ranked_for_ticker:
            status = str(contract.get("actionability_status") or contract.get("recommendation_status") or "").lower()
            if status == "paper_eligible":
                response["paper_eligible_contracts"].append(contract)
            elif status == "research_only":
                response["research_only_contracts"].append(contract)
            else:
                response["blocked_contracts"].append(contract)

    response["paper_eligible_contracts"] = _sort_contracts(response["paper_eligible_contracts"])[: max_underlyings * max_contracts]
    response["research_only_contracts"] = _sort_contracts(response["research_only_contracts"])[: max_underlyings * max_contracts]
    response["blocked_contracts"] = _sort_contracts(response["blocked_contracts"])[: max_underlyings * max_contracts]
    response["underlying_watchlist"] = list({str(row.get("ticker")): row for row in response["underlying_watchlist"] if row.get("ticker")}.values())

    exact_count = len(response["paper_eligible_contracts"]) + len(response["research_only_contracts"]) + len(response["blocked_contracts"])
    if exact_count:
        response["status"] = "available" if provider_failures == 0 else "partial"
        response["provider_status"] = "available" if provider_failures == 0 and not response["missing_requirements"] else "degraded"
    elif response["underlying_watchlist"]:
        response["status"] = "partial"
        response["provider_status"] = "degraded" if provider_success else "unavailable"
    else:
        response["status"] = "unavailable"
        response["provider_status"] = "unavailable" if provider_failures else "unknown"

    if not options_final_eligibility and exact_count:
        response["warnings"].append("Exact option research is available, but final option paper eligibility remains false.")
    if metadata_only and not exact_count:
        response["missing_requirements"].append("Option metadata was available, but bid/ask, IV, Greeks, liquidity, and fill quality were insufficient for exact contract ranking.")

    response["missing_requirements"] = _unique_texts(response["missing_requirements"])
    response["warnings"] = _unique_texts(response["warnings"])
    response["errors"] = _unique_texts(response["errors"])
    response["ok"] = response["status"] in {"available", "partial", "unavailable", "disabled"}
    return response
