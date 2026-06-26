from __future__ import annotations

from copy import deepcopy
from importlib.util import find_spec
from statistics import median
from typing import Any
from uuid import uuid4
import hashlib
import json
import os

from ideas import build_assistant_trade_response, build_best_available_ideas, format_best_ideas_response
from learning import active_policy_defaults, record_adaptive_research_execution
from research.research_orchestrator import build_current_research, empty_research_response, scopes_from_research_preferences
from scanner.options_discovery import discover_option_ideas, empty_option_discovery_response

from .plan_executor import build_combined_universe, execute_scan_plan
from .policy_validator import POLICY_LIMITS, SUPPORTED_PROFILES, SUPPORTED_UNIVERSES, validate_scan_plan
from .refinement_models import REFINEMENT_PROPOSAL_VERSION, RefinementProposalModel, empty_refinement_proposal
from .refinement_prompts import build_refinement_system_prompt, build_refinement_user_payload
from .scan_plan import ScanPlan


ADAPTIVE_EXECUTION_VERSION = "adaptive_scan_v1"
SCAN_PASS_EVALUATION_VERSION = "scan_pass_evaluation_v1"
DEFAULT_SUFFICIENT_STOCK_IDEA_COUNT = 3
DEFAULT_SUFFICIENT_OPTION_CONTRACT_COUNT = 1
DEFAULT_MINIMUM_RESEARCH_OPPORTUNITY_SCORE = 65.0
REFINEMENT_PROVIDER_CHOICES = {"auto", "openai", "deterministic"}
DEFAULT_OPENAI_REFINEMENT_MODEL = "gpt-4.1-mini"


def _as_dict(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list:
    return value if isinstance(value, list) else []


def _safe_float(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _safe_int(value: Any, default: int = 0) -> int:
    numeric = _safe_float(value)
    return int(numeric) if numeric is not None else default


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


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe(nested) for key, nested in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, tuple):
        return [_json_safe(item) for item in value]
    return value


def _normalized_provider(provider: str | None) -> str:
    requested = str(provider or os.getenv("AI_REFINEMENT_PROVIDER") or "auto").strip().lower()
    return requested if requested in REFINEMENT_PROVIDER_CHOICES else "auto"


def _openai_refinement_model() -> str:
    return str(os.getenv("OPENAI_REFINEMENT_MODEL") or os.getenv("OPENAI_PLANNER_MODEL") or DEFAULT_OPENAI_REFINEMENT_MODEL).strip() or DEFAULT_OPENAI_REFINEMENT_MODEL


def _openai_sdk_available() -> bool:
    return find_spec("openai") is not None


def _openai_api_key_configured() -> bool:
    return bool(os.getenv("OPENAI_API_KEY"))


def _create_openai_client(api_key: str, timeout: float = 20.0):
    from openai import OpenAI

    return OpenAI(api_key=api_key, timeout=timeout)


def _base_response(policy_validation: dict, root_run_id: str) -> dict:
    approved_plan = _as_dict(policy_validation.get("approved_plan"))
    return {
        "ok": False,
        "adaptive_execution_version": ADAPTIVE_EXECUTION_VERSION,
        "paper_trading_only": True,
        "brokerage_execution_enabled": False,
        "status": "failed",
        "request_id": approved_plan.get("request_id"),
        "root_run_id": root_run_id,
        "initial_plan": policy_validation.get("proposed_plan", {}),
        "initial_policy_validation": policy_validation,
        "max_passes": 1,
        "passes_executed": 0,
        "stop_reason": "",
        "refinement_used": False,
        "refinement_provider": "none",
        "passes": [],
        "consolidated_result": {},
        "best_available_ideas": {},
        "assistant_response": {},
        "option_discovery": empty_option_discovery_response(requested=False, reason="Option discovery has not run."),
        "research": empty_research_response(status="disabled", provider="none", request_id=root_run_id, warnings=["Current research has not run."]),
        "formatted_response": "",
        "active_policy_version": None,
        "active_policy_fingerprint": None,
        "learning_recording": {},
        "warnings": list(_as_list(policy_validation.get("warnings"))),
        "errors": list(_as_list(policy_validation.get("errors"))),
    }


def create_refinement_scope_lock(initial_approved_plan: dict, max_passes: int) -> dict:
    requested = str(initial_approved_plan.get("requested_instrument") or "stocks").lower()
    return {
        "scope_lock_version": "refinement_scope_lock_v1",
        "objective": initial_approved_plan.get("objective"),
        "requested_instrument": requested,
        "time_horizon": initial_approved_plan.get("time_horizon"),
        "custom_tickers": list(_as_list(initial_approved_plan.get("custom_tickers"))),
        "stock_only": requested == "stocks" and not bool(initial_approved_plan.get("include_options")),
        "options_only": requested == "options",
        "include_options": bool(initial_approved_plan.get("include_options")),
        "prefer_options": bool(initial_approved_plan.get("prefer_options")),
        "research_preferences": deepcopy(_as_dict(initial_approved_plan.get("research_preferences"))),
        "paper_trading_only": True,
        "brokerage_execution_enabled": False,
        "auto_log": False,
        "max_passes": max_passes,
        "immutable_safety_policy": True,
    }


def plan_fingerprint(plan: dict, effective_tickers: list[str] | None = None) -> str:
    option_preferences = _as_dict(plan.get("option_preferences"))
    soft = _as_dict(plan.get("soft_adjustments"))
    payload = {
        "requested_instrument": plan.get("requested_instrument"),
        "objective": plan.get("objective"),
        "universes": sorted(str(item) for item in _as_list(plan.get("universes"))),
        "custom_tickers": sorted(str(item).upper() for item in _as_list(plan.get("custom_tickers"))),
        "profiles": sorted(str(item) for item in _as_list(plan.get("profiles"))),
        "max_tickers": plan.get("max_tickers"),
        "max_candidates": plan.get("max_candidates"),
        "include_options": bool(plan.get("include_options")),
        "option_preferences": option_preferences,
        "profile_weights": _as_dict(soft.get("profile_weights")),
        "opportunity_weights": _as_dict(soft.get("opportunity_weights")),
        "effective_tickers": sorted(str(item).upper() for item in (effective_tickers or [])),
    }
    encoded = json.dumps(_json_safe(payload), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:16]


def _provider_status(execution_result: dict, best_ideas: dict) -> str:
    assistant = _as_dict(execution_result.get("assistant_response"))
    market = _as_dict(assistant.get("market_state"))
    status = str(market.get("provider_status") or "").lower()
    if status in {"available", "degraded", "unavailable", "unknown"}:
        return status
    if best_ideas.get("ranking_status") == "unavailable":
        issues = " ".join(str(item).lower() for item in _as_list(best_ideas.get("system_issues")) + _as_list(best_ideas.get("data_missing")))
        if any(token in issues for token in ("provider", "ibkr", "tws", "market data", "historical bars", "quote")):
            return "unavailable"
    if best_ideas.get("system_issues") or best_ideas.get("data_missing"):
        return "degraded"
    return "available" if best_ideas.get("ranking_status") == "available" else "unknown"


def _compact_failed_constraints(rows: list[dict]) -> dict:
    counts: dict[str, int] = {}
    for row in rows:
        source = _as_dict(row.get("raw_candidate")) or row
        constraints = []
        constraints.extend(_as_list(row.get("failed_constraints")))
        constraints.extend(_as_list(source.get("failed_constraints")))
        constraints.extend(_as_list(_as_dict(source.get("constraint_results")).get("failed_constraints")))
        for constraint in constraints:
            key = str(constraint or "").strip()
            if key:
                counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _data_failure_count(execution_result: dict) -> int:
    trading = _as_dict(execution_result.get("trading_result"))
    scan = _as_dict(trading.get("scan_result"))
    rows = _as_list(scan.get("rejected_candidates")) + _as_list(scan.get("watchlist_candidates"))
    count = 0
    for row in rows:
        quality = _as_dict(row.get("data_quality")) if isinstance(row, dict) else {}
        if quality.get("quality_label") == "unavailable" or "scanner_error" in _as_list(row.get("failed_constraints")):
            count += 1
    return count


def evaluate_scan_pass(
    execution_result: dict,
    approved_plan: dict,
    pass_number: int,
) -> dict:
    result = _as_dict(execution_result)
    best = _as_dict(result.get("best_available_ideas"))
    assistant = _as_dict(result.get("assistant_response"))
    top_stocks = _as_list(assistant.get("top_stocks"))
    top_options = _as_list(assistant.get("top_options"))
    paper_eligible = _as_list(best.get("paper_eligible"))
    stock_watchlist = _as_list(best.get("stock_watchlist"))
    blocked = _as_list(best.get("blocked_but_interesting"))
    option_watchlist = _as_list(best.get("option_underlying_watchlist"))
    exact_options = [
        row for row in top_options
        if isinstance(row, dict) and row.get("option_contract") and row.get("bid") is not None and row.get("ask") is not None
    ]

    stock_scores = [
        _safe_float(row.get("opportunity_score"))
        for row in top_stocks
        if isinstance(row, dict) and _safe_float(row.get("opportunity_score")) is not None
    ]
    option_scores = [
        _safe_float(row.get("opportunity_score"))
        for row in top_options
        if isinstance(row, dict) and _safe_float(row.get("opportunity_score")) is not None
    ]
    provider_status = _provider_status(result, best)
    ranking_status = str(best.get("ranking_status") or "no_qualifying_ideas")
    paper_count = len(paper_eligible)
    legitimate_ranked_count = paper_count + len(stock_watchlist) + len(blocked) + len(exact_options) + len(option_watchlist)
    requested = str(approved_plan.get("requested_instrument") or "stocks").lower()
    objective = str(approved_plan.get("objective") or "best_ideas").lower()
    partial = bool(_as_dict(result.get("execution_summary")).get("partial_results") or _as_dict(assistant.get("market_state")).get("partial_results"))

    sufficient = False
    reasons: list[str] = []
    warnings: list[str] = []
    if ranking_status == "unavailable" or provider_status == "unavailable":
        reasons.append("Provider or essential market data is unavailable; refinement is unsafe.")
    elif paper_count > 0:
        sufficient = True
        reasons.append("At least one paper-eligible idea passed strict gates.")
    elif objective == "ticker_review":
        sufficient = True
        reasons.append("Ticker review scope is locked to one deterministic pass.")
    elif requested == "options" and len(exact_options) >= DEFAULT_SUFFICIENT_OPTION_CONTRACT_COUNT:
        sufficient = True
        reasons.append("At least one exact rankable option contract is available.")
    elif requested != "options" and len(top_stocks) >= DEFAULT_SUFFICIENT_STOCK_IDEA_COUNT:
        sufficient = True
        reasons.append("Sufficient legitimate stock research ideas are available.")
    elif stock_scores and sum(1 for score in stock_scores if score >= DEFAULT_MINIMUM_RESEARCH_OPPORTUNITY_SCORE) >= DEFAULT_SUFFICIENT_STOCK_IDEA_COUNT:
        sufficient = True
        reasons.append("Enough stock ideas cleared the research opportunity threshold.")
    else:
        reasons.append("Legitimate rankings are sparse or weak; one bounded refinement may help.")

    if partial:
        warnings.append("Pass returned partial results; only refine if distinct safe coverage remains.")

    refinement_allowed = (
        not sufficient
        and ranking_status != "unavailable"
        and provider_status != "unavailable"
        and objective != "ticker_review"
        and not (partial and legitimate_ranked_count == 0)
    )
    if not refinement_allowed and not sufficient and not reasons:
        reasons.append("Refinement is not allowed by deterministic stop conditions.")

    if not refinement_allowed:
        action = "stop"
    elif requested in {"options", "both"} and not exact_options:
        action = "expand_option_research"
    elif len(stock_watchlist) + len(blocked) < DEFAULT_SUFFICIENT_STOCK_IDEA_COUNT:
        action = "broaden_universe"
    else:
        action = "change_profiles"

    return {
        "evaluation_version": SCAN_PASS_EVALUATION_VERSION,
        "provider_status": provider_status if provider_status in {"available", "degraded", "unavailable", "unknown"} else "unknown",
        "ranking_status": ranking_status if ranking_status in {"available", "unavailable", "no_qualifying_ideas"} else "no_qualifying_ideas",
        "paper_eligible_count": paper_count,
        "stock_watchlist_count": len(stock_watchlist),
        "blocked_research_count": len(blocked),
        "exact_option_count": len(exact_options),
        "option_underlying_watchlist_count": len(option_watchlist),
        "legitimate_ranked_count": legitimate_ranked_count,
        "top_stock_opportunity_score": max(stock_scores) if stock_scores else None,
        "top_option_opportunity_score": max(option_scores) if option_scores else None,
        "median_stock_opportunity_score": median(stock_scores) if stock_scores else None,
        "failed_constraint_counts": _compact_failed_constraints(blocked + stock_watchlist),
        "data_failure_count": _data_failure_count(result),
        "partial_results": partial,
        "sufficient_results": sufficient,
        "refinement_allowed": refinement_allowed,
        "recommended_action": action,
        "reasons": _unique_texts(reasons),
        "warnings": _unique_texts(warnings),
    }


def _pass_summary(pass_result: dict) -> dict:
    evaluation = _as_dict(pass_result.get("evaluation"))
    summary = _as_dict(pass_result.get("execution_summary"))
    return {
        "pass_number": pass_result.get("pass_number"),
        "plan_fingerprint": pass_result.get("plan_fingerprint"),
        "universes_used": summary.get("universes_used"),
        "profiles_run": summary.get("profiles_run"),
        "ticker_count_executed": summary.get("ticker_count_executed"),
        "ranking_status": evaluation.get("ranking_status"),
        "provider_status": evaluation.get("provider_status"),
        "paper_eligible_count": evaluation.get("paper_eligible_count"),
        "legitimate_ranked_count": evaluation.get("legitimate_ranked_count"),
        "failed_constraint_counts": evaluation.get("failed_constraint_counts"),
    }


def _deterministic_refinement(
    initial_plan: dict,
    current_plan: dict,
    pass_evaluation: dict,
    prior_pass_summaries: list[dict],
) -> dict:
    if not pass_evaluation.get("refinement_allowed"):
        return empty_refinement_proposal("stop", "Deterministic stop conditions do not allow refinement.")
    if current_plan.get("objective") == "ticker_review" or current_plan.get("custom_tickers"):
        return empty_refinement_proposal("stop", "Explicit ticker/custom scope cannot broaden into unrelated universes.")

    current_universes = [str(item) for item in _as_list(current_plan.get("universes"))]
    used_universes: set[str] = set(current_universes)
    for prior in prior_pass_summaries:
        used_universes.update(str(item) for item in _as_list(prior.get("universes_used")))
    universe_order = ["growth", "sp500_sample", "active", "tech", "large_cap", "mega_cap"]
    new_universe = next((item for item in universe_order if item not in used_universes and item in SUPPORTED_UNIVERSES), None)

    adjustments: dict[str, Any] = {}
    if new_universe:
        adjustments["universes"] = [new_universe]
        adjustments["max_tickers"] = min(POLICY_LIMITS["max_tickers"]["max"], max(_safe_int(current_plan.get("max_tickers"), 100), 50))
        adjustments["max_candidates"] = min(POLICY_LIMITS["max_candidates"]["max"], max(_safe_int(current_plan.get("max_candidates"), 20), 30))
        reason = f"Broaden into unscanned approved universe '{new_universe}' while preserving scope and gates."
    else:
        current_profiles = set(str(item) for item in _as_list(current_plan.get("profiles")))
        remaining_profiles = [profile for profile in SUPPORTED_PROFILES if profile not in current_profiles]
        if not remaining_profiles:
            return empty_refinement_proposal("stop", "No materially distinct approved universe or profile coverage remains.")
        adjustments["profiles"] = remaining_profiles[:2]
        adjustments["universes"] = current_universes or list(_as_list(initial_plan.get("universes"))) or ["large_cap"]
        reason = "Use a complementary supported profile subset without changing hard gates."

    if current_plan.get("include_options"):
        option_preferences = _as_dict(current_plan.get("option_preferences"))
        adjustments["max_option_contracts_per_ticker"] = min(
            POLICY_LIMITS["max_contracts_per_ticker"]["max"],
            max(_safe_int(option_preferences.get("max_contracts_per_ticker"), 3), 5),
        )
        adjustments["option_min_dte"] = max(POLICY_LIMITS["option_min_dte"]["min"], _safe_int(option_preferences.get("min_dte"), 14) - 7)
        adjustments["option_max_dte"] = min(POLICY_LIMITS["option_max_dte"]["max"], _safe_int(option_preferences.get("max_dte"), 56) + 14)
        adjustments["max_option_underlyings"] = 7

    return {
        "proposal_version": REFINEMENT_PROPOSAL_VERSION,
        "action": "refine",
        "reasoning_summary": reason,
        "adjustments": adjustments,
    }


def _safe_openai_summary(value: Any, limit: int = 500) -> str:
    text = str(value or "").strip()
    return text if len(text) <= limit else f"{text[: limit - 3]}..."


def _propose_with_openai(
    *,
    initial_plan: dict,
    current_plan: dict,
    pass_evaluation: dict,
    prior_pass_summaries: list[dict],
    runtime_context: dict | None,
    remaining_pass_budget: int,
) -> tuple[dict, dict]:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OpenAI refinement API key is not configured.")
    client = _create_openai_client(api_key=api_key)
    model = _openai_refinement_model()
    response = client.responses.parse(
        model=model,
        input=[
            {"role": "system", "content": build_refinement_system_prompt()},
            {
                "role": "user",
                "content": build_refinement_user_payload(
                    initial_plan=initial_plan,
                    current_plan=current_plan,
                    pass_evaluation=pass_evaluation,
                    prior_pass_summaries=prior_pass_summaries,
                    remaining_pass_budget=remaining_pass_budget,
                    runtime_context=runtime_context,
                ),
            },
        ],
        text_format=RefinementProposalModel,
    )
    parsed = getattr(response, "output_parsed", None)
    if parsed is None:
        raise RuntimeError("OpenAI refinement returned no structured proposal.")
    payload = parsed.model_dump(mode="python") if hasattr(parsed, "model_dump") else deepcopy(_as_dict(parsed))
    payload["proposal_version"] = REFINEMENT_PROPOSAL_VERSION
    usage = getattr(response, "usage", None)
    if hasattr(usage, "model_dump"):
        usage = usage.model_dump(mode="json")
    elif not isinstance(usage, dict):
        usage = {}
    return payload, {"model": model, "usage": usage}


def propose_scan_refinement(
    initial_plan: dict,
    current_plan: dict,
    pass_evaluation: dict,
    prior_pass_summaries: list[dict],
    runtime_context: dict | None = None,
    provider: str | None = None,
) -> dict:
    selected = _normalized_provider(provider)
    result = {
        "ok": True,
        "proposal_version": REFINEMENT_PROPOSAL_VERSION,
        "provider": selected,
        "model": None,
        "fallback_used": False,
        "proposal": empty_refinement_proposal("stop", "No refinement proposed."),
        "warnings": [],
        "errors": [],
        "usage": {},
    }
    if selected == "deterministic":
        result["provider"] = "deterministic"
        result["proposal"] = _deterministic_refinement(initial_plan, current_plan, pass_evaluation, prior_pass_summaries)
        return result

    should_try_openai = selected == "openai" or (selected == "auto" and _openai_sdk_available() and _openai_api_key_configured())
    if should_try_openai:
        try:
            proposal, meta = _propose_with_openai(
                initial_plan=initial_plan,
                current_plan=current_plan,
                pass_evaluation=pass_evaluation,
                prior_pass_summaries=prior_pass_summaries,
                runtime_context=runtime_context,
                remaining_pass_budget=max(0, _safe_int(_as_dict(initial_plan.get("refinement")).get("max_passes"), 1) - len(prior_pass_summaries)),
            )
            result.update({"provider": "openai", "model": meta.get("model"), "proposal": proposal, "usage": meta.get("usage", {})})
            return result
        except Exception as exc:
            result["warnings"].append(f"OpenAI refinement unavailable; deterministic fallback used: {_safe_openai_summary(exc, 180)}")
            result["fallback_used"] = True
            result["provider"] = "deterministic"
            result["proposal"] = _deterministic_refinement(initial_plan, current_plan, pass_evaluation, prior_pass_summaries)
            return result

    result["provider"] = "deterministic"
    result["fallback_used"] = selected != "deterministic"
    if not _openai_api_key_configured():
        result["warnings"].append("OpenAI refinement API key is not configured; deterministic fallback used.")
    if not _openai_sdk_available():
        result["warnings"].append("OpenAI SDK is not installed; deterministic fallback used.")
    result["proposal"] = _deterministic_refinement(initial_plan, current_plan, pass_evaluation, prior_pass_summaries)
    return result


def _apply_refinement_proposal(current_plan: dict, proposal: dict, scope_lock: dict) -> tuple[dict, dict]:
    diagnostics = {
        "scope_lock_version": scope_lock.get("scope_lock_version"),
        "ok": True,
        "applied_adjustments": [],
        "rejected_adjustments": [],
        "violations": [],
    }
    proposed = deepcopy(current_plan)
    if _as_dict(proposal).get("action") != "refine":
        diagnostics["ok"] = False
        diagnostics["violations"].append("Proposal action is stop; no refined plan was created.")
        return proposed, diagnostics

    adjustments = _as_dict(_as_dict(proposal).get("adjustments"))
    custom_locked = bool(scope_lock.get("custom_tickers"))
    for field in ("universes", "profiles"):
        value = adjustments.get(field)
        if value is None:
            continue
        if field == "universes" and custom_locked:
            diagnostics["rejected_adjustments"].append({"field": field, "reason": "Explicit custom ticker scope is locked."})
            continue
        proposed[field] = list(_as_list(value))
        diagnostics["applied_adjustments"].append(field)

    for field in ("max_tickers", "max_candidates"):
        value = adjustments.get(field)
        if value is not None:
            proposed[field] = value
            diagnostics["applied_adjustments"].append(field)

    soft = deepcopy(_as_dict(proposed.get("soft_adjustments")))
    if isinstance(adjustments.get("profile_weights"), dict):
        soft["profile_weights"] = adjustments["profile_weights"]
        diagnostics["applied_adjustments"].append("profile_weights")
    if isinstance(adjustments.get("opportunity_weights"), dict):
        soft["opportunity_weights"] = adjustments["opportunity_weights"]
        diagnostics["applied_adjustments"].append("opportunity_weights")
    proposed["soft_adjustments"] = soft

    option_preferences = deepcopy(_as_dict(proposed.get("option_preferences")))
    mapping = {
        "option_min_dte": "min_dte",
        "option_max_dte": "max_dte",
        "max_option_contracts_per_ticker": "max_contracts_per_ticker",
    }
    for source, target in mapping.items():
        if adjustments.get(source) is not None:
            option_preferences[target] = adjustments[source]
            diagnostics["applied_adjustments"].append(source)
    proposed["option_preferences"] = option_preferences

    # Reapply immutable scope locks regardless of proposal content.
    for field in ("objective", "requested_instrument", "time_horizon"):
        proposed[field] = scope_lock.get(field)
    proposed["paper_trading_only"] = True
    proposed["brokerage_execution_enabled"] = False
    proposed["auto_log"] = False
    proposed["custom_tickers"] = list(scope_lock.get("custom_tickers") or []) if custom_locked else list(_as_list(proposed.get("custom_tickers")))
    if scope_lock.get("stock_only"):
        proposed["include_options"] = False
        proposed["prefer_options"] = False
    elif scope_lock.get("options_only"):
        proposed["include_options"] = True
        proposed["prefer_options"] = True
    else:
        proposed["include_options"] = bool(scope_lock.get("include_options"))
        proposed["prefer_options"] = bool(scope_lock.get("prefer_options"))
    proposed["research_preferences"] = deepcopy(scope_lock.get("research_preferences") or {})
    proposed["refinement"] = {
        **_as_dict(proposed.get("refinement")),
        "max_passes": scope_lock.get("max_passes"),
    }

    unsafe = [field for field in ("place_orders", "order_execution_enabled", "disable_data_quality", "bypass_constraints", "auto_log_blocked") if field in proposed]
    for field in unsafe:
        proposed.pop(field, None)
        diagnostics["rejected_adjustments"].append({"field": field, "reason": "Unsafe refinement field removed."})
    return proposed, diagnostics


def _coverage_diagnostics(universe_result: dict, profiles: list[str], previous_pairs: set[tuple[str, str]]) -> dict:
    tickers = [str(item).upper() for item in _as_list(universe_result.get("tickers"))]
    profile_rows = [str(item) for item in profiles]
    new_tickers = []
    reused_tickers = []
    repeated = 0
    for ticker in tickers:
        ticker_new = False
        for profile in profile_rows:
            pair = (ticker, profile)
            if pair in previous_pairs:
                repeated += 1
            else:
                ticker_new = True
        if ticker_new:
            new_tickers.append(ticker)
        else:
            reused_tickers.append(ticker)
    return {
        "new_tickers": new_tickers,
        "reused_tickers": reused_tickers,
        "new_profiles": profile_rows,
        "repeated_pair_count_avoided": repeated,
    }


def _row_sort_key(row: dict) -> tuple[float, float, float, int]:
    return (
        _safe_float(row.get("opportunity_score")) or _safe_float(row.get("idea_score")) or -1.0,
        _safe_float(row.get("score")) or _safe_float(row.get("engine_score")) or -1.0,
        _safe_float(row.get("risk_reward")) or -1.0,
        -_safe_int(row.get("source_pass"), 999),
    )


def _dedupe_research_rows(rows: list[dict]) -> list[dict]:
    best: dict[str, dict] = {}
    for row in rows:
        ticker = str(row.get("ticker") or "").upper()
        setup = str(row.get("setup_type") or row.get("setup") or row.get("strategy") or "").lower()
        key = f"{ticker}:{setup}"
        if not ticker:
            continue
        if key not in best or _row_sort_key(row) > _row_sort_key(best[key]):
            best[key] = row
    return sorted(best.values(), key=_row_sort_key, reverse=True)


def _raw_with_source(row: dict, source_pass: int) -> dict:
    raw = deepcopy(_as_dict(row.get("raw_candidate")) or row)
    raw["source_pass"] = source_pass
    return raw


def _synthetic_trading_result_from_passes(passes: list[dict], approved_plan: dict, max_final_trades: int) -> dict:
    paper: list[dict] = []
    watchlist: list[dict] = []
    blocked: list[dict] = []
    data_missing: list[str] = []
    system_issues: list[str] = []
    for pass_result in passes:
        pass_number = _safe_int(pass_result.get("pass_number"), 1)
        best = _as_dict(_as_dict(pass_result.get("execution_result")).get("best_available_ideas"))
        paper.extend(_raw_with_source(row, pass_number) for row in _as_list(best.get("paper_eligible")) if isinstance(row, dict) and str(row.get("asset_type", "stock")).lower() != "option")
        watchlist.extend(_raw_with_source(row, pass_number) for row in _as_list(best.get("stock_watchlist")) if isinstance(row, dict))
        blocked.extend(_raw_with_source(row, pass_number) for row in _as_list(best.get("blocked_but_interesting")) if isinstance(row, dict) and str(row.get("asset_type", "stock")).lower() != "option")
        data_missing.extend(_as_list(best.get("data_missing")))
        system_issues.extend(_as_list(best.get("system_issues")))

    paper = _dedupe_research_rows(paper)[:max_final_trades]
    watchlist = _dedupe_research_rows(watchlist)
    blocked = _dedupe_research_rows(blocked)
    return {
        "ok": True,
        "mode": "adaptive_consolidated",
        "decision_result": {
            "ok": True,
            "final_recommendations": paper,
            "logged_recommendations": [],
            "not_selected": [],
        },
        "selection_result": {
            "ok": True,
            "selected_trades": paper,
            "watchlist_alternatives": watchlist,
            "rejected_candidates": blocked,
        },
        "scan_result": {
            "ok": True,
            "watchlist_candidates": watchlist,
            "rejected_candidates": blocked,
            "data_quality_summary": {
                "warnings": _unique_texts(data_missing),
                "errors": _unique_texts(system_issues),
            },
        },
        "summary": {
            "profiles_run": list(_as_list(approved_plan.get("profiles"))),
            "selected_count": len(paper),
            "logged_count": 0,
            "adaptive_consolidated": True,
        },
        "errors": [],
        "adaptive_data_missing": _unique_texts(data_missing),
        "adaptive_system_issues": _unique_texts(system_issues),
    }


def _research_candidate_context(assistant_response: dict, max_tickers: int = 3) -> tuple[list[str], list[dict]]:
    tickers: list[str] = []
    context: list[dict] = []
    for row in _as_list(assistant_response.get("top_stocks")) + _as_list(assistant_response.get("top_options")):
        if not isinstance(row, dict):
            continue
        ticker = str(row.get("ticker") or "").upper()
        if not ticker or ticker in tickers:
            continue
        tickers.append(ticker)
        context.append(
            {
                "ticker": ticker,
                "asset_type": row.get("asset_type"),
                "status": row.get("status"),
                "rank": row.get("rank"),
                "setup": row.get("setup") or row.get("strategy"),
                "opportunity_score": row.get("opportunity_score"),
            }
        )
        if len(tickers) >= max_tickers:
            break
    return tickers, context


def _run_final_research(approved_plan: dict, assistant_response: dict, root_run_id: str, warnings: list[str]) -> dict:
    scopes = scopes_from_research_preferences(_as_dict(approved_plan.get("research_preferences")))
    if not scopes:
        return empty_research_response(status="disabled", provider="none", request_id=root_run_id, scopes=[], warnings=["Current research was not requested."])
    tickers, context = _research_candidate_context(assistant_response)
    if not tickers and str(approved_plan.get("objective")) == "ticker_review":
        tickers = [str(item).upper() for item in _as_list(approved_plan.get("custom_tickers")) if str(item).strip()]
        context = [{"ticker": ticker, "asset_type": "stock", "status": "ticker_review"} for ticker in tickers]
    if not tickers:
        warnings.append("Current research was requested, but no final consolidated ranked tickers were available.")
        return empty_research_response(status="unavailable", provider="none", request_id=root_run_id, scopes=scopes, warnings=["No final consolidated ranked tickers were available."])
    return build_current_research(tickers, scopes=scopes, candidate_context=context, request_id=root_run_id)


def _finalize_consolidated_response(
    *,
    passes: list[dict],
    approved_plan: dict,
    execution_config: dict,
    runtime_context: dict | None,
    root_run_id: str,
    stop_reason: str,
    refinement_used: bool,
    warnings: list[str],
) -> tuple[dict, dict, dict, dict, str]:
    consolidated = _synthetic_trading_result_from_passes(passes, approved_plan, _safe_int(approved_plan.get("max_final_trades"), 5))
    preliminary_best = build_best_available_ideas(consolidated, config={"include_options": False})
    option_discovery = empty_option_discovery_response(requested=False, reason="Option discovery disabled for stock-only request.")
    if bool(execution_config.get("include_options")):
        stock_candidates = []
        for bucket in ("paper_eligible", "stock_watchlist", "blocked_but_interesting"):
            stock_candidates.extend(row for row in _as_list(preliminary_best.get(bucket)) if isinstance(row, dict) and str(row.get("asset_type", "stock")).lower() != "option")
        option_discovery = discover_option_ideas(
            stock_candidates,
            explicit_tickers=_as_list(approved_plan.get("custom_tickers")) if approved_plan.get("objective") == "ticker_review" else None,
            option_preferences=_as_dict(approved_plan.get("option_preferences")),
            runtime_context={
                **_as_dict(runtime_context),
                "requested": True,
                "safe_to_run_options": bool(execution_config.get("options_final_eligibility")),
                "options_final_eligibility": bool(execution_config.get("options_final_eligibility")),
            },
            max_underlyings=7,
            max_contracts_per_ticker=_safe_int(execution_config.get("max_option_contracts_per_trade"), 3),
        )
    consolidated["option_discovery"] = option_discovery
    best = build_best_available_ideas(
        consolidated,
        config={
            "include_options": bool(execution_config.get("include_options")),
            "option_discovery": option_discovery,
            "opportunity_ranker": {"weights": _as_dict(execution_config.get("opportunity_weights"))},
        },
    )
    assistant = build_assistant_trade_response(best, trading_result=consolidated, requested_instrument=approved_plan.get("requested_instrument", "auto"), run_id=root_run_id)
    research = _run_final_research(approved_plan, assistant, root_run_id, warnings)
    assistant = build_assistant_trade_response(best, trading_result=consolidated, requested_instrument=approved_plan.get("requested_instrument", "auto"), run_id=root_run_id, research=research)
    changes = []
    for pass_result in passes:
        proposal = _as_dict(pass_result.get("refinement_proposal"))
        proposal_payload = _as_dict(proposal.get("proposal"))
        if proposal_payload.get("action") == "refine":
            changes.append(
                {
                    "after_pass": pass_result.get("pass_number"),
                    "reason": proposal_payload.get("reasoning_summary"),
                    "adjustments": proposal_payload.get("adjustments"),
                }
            )
    assistant["refinement"] = {
        "used": bool(refinement_used),
        "passes_executed": len(passes),
        "stop_reason": stop_reason,
        "changes": changes,
        "warnings": _unique_texts(warnings),
    }
    formatted = format_best_ideas_response(assistant)
    return consolidated, best, assistant, research, formatted


def _status_from_stop(stop_reason: str, passes: list[dict], errors: list[str]) -> str:
    if errors:
        return "failed"
    if any(_as_dict(pass_result.get("evaluation")).get("ranking_status") == "unavailable" for pass_result in passes):
        return "unavailable"
    return "completed_with_warnings" if any(pass_result.get("warnings") for pass_result in passes) or "warning" in stop_reason.lower() else "completed"


def execute_adaptive_scan_plan(
    proposed_plan: ScanPlan | dict,
    runtime_context: dict | None = None,
    db_path: str = "strategy_library.db",
    message: str | None = None,
    provider: str | None = None,
    internal_controls: dict | None = None,
) -> dict:
    initial_validation = validate_scan_plan(proposed_plan, runtime_context=runtime_context)
    root_run_id = _as_dict(initial_validation.get("approved_plan")).get("request_id") or str(uuid4())
    response = _base_response(initial_validation, root_run_id)
    warnings = response["warnings"]
    errors = response["errors"]
    active_policy = active_policy_defaults(db_path)
    response["active_policy_version"] = active_policy.get("active_policy_version")
    response["active_policy_fingerprint"] = active_policy.get("active_policy_fingerprint")
    if active_policy.get("errors"):
        warnings.extend(str(item) for item in active_policy.get("errors", []))
    if not initial_validation.get("ok"):
        response["stop_reason"] = "Initial ScanPlan validation failed."
        response["errors"] = errors
        return response

    initial_approved = _as_dict(initial_validation.get("approved_plan"))
    initial_execution_config = _as_dict(initial_validation.get("execution_config"))
    max_passes = max(1, min(3, _safe_int(_as_dict(initial_approved.get("refinement")).get("max_passes"), 1)))
    if str(initial_approved.get("objective")) == "ticker_review" or initial_approved.get("custom_tickers"):
        max_passes = 1
    response["max_passes"] = max_passes
    scope_lock = create_refinement_scope_lock(initial_approved, max_passes)

    current_plan = deepcopy(initial_approved)
    seen_fingerprints: set[str] = set()
    previous_pairs: set[tuple[str, str]] = set()
    stop_reason = ""
    refinement_used = False
    refinement_provider = "none"
    controls = _as_dict(internal_controls)

    for pass_number in range(1, max_passes + 1):
        pass_plan = deepcopy(current_plan)
        pass_plan["request_id"] = f"{root_run_id}:pass-{pass_number}"
        pass_validation = validate_scan_plan(pass_plan, runtime_context=runtime_context)
        approved = _as_dict(pass_validation.get("approved_plan"))
        execution_config = _as_dict(pass_validation.get("execution_config"))
        universe_result = build_combined_universe(execution_config)
        effective_tickers = _as_list(universe_result.get("tickers"))
        fingerprint = plan_fingerprint(approved, effective_tickers=effective_tickers)
        pass_result = {
            "pass_number": pass_number,
            "run_id": approved.get("request_id") or f"{root_run_id}:pass-{pass_number}",
            "parent_run_id": root_run_id if pass_number == 1 else response["passes"][-1].get("run_id") if response["passes"] else root_run_id,
            "plan_fingerprint": fingerprint,
            "proposed_plan": deepcopy(pass_plan),
            "policy_validation": pass_validation,
            "approved_plan": approved,
            "execution_summary": {},
            "evaluation": {},
            "refinement_proposal": None,
            "result_summary": {},
            "execution_result": {},
            "warnings": list(_as_list(pass_validation.get("warnings"))),
            "errors": list(_as_list(pass_validation.get("errors"))),
        }
        if not pass_validation.get("ok"):
            stop_reason = "Refined ScanPlan validation failed."
            pass_result["errors"].extend(_as_list(pass_validation.get("errors")))
            response["passes"].append(pass_result)
            break
        if fingerprint in seen_fingerprints:
            stop_reason = "Duplicate plan fingerprint detected; adaptive loop stopped before repeating coverage."
            pass_result["warnings"].append(stop_reason)
            response["passes"].append(pass_result)
            break
        seen_fingerprints.add(fingerprint)

        coverage = _coverage_diagnostics(universe_result, list(_as_list(execution_config.get("profiles"))), previous_pairs)
        for ticker in _as_list(universe_result.get("tickers")):
            for profile in _as_list(execution_config.get("profiles")):
                previous_pairs.add((str(ticker).upper(), str(profile)))

        execution_result = execute_scan_plan(
            approved,
            runtime_context=runtime_context,
            db_path=db_path,
            internal_controls={
                **controls,
                "run_current_research": False,
                "run_option_discovery": False,
                "record_learning": False,
            },
        )
        evaluation = evaluate_scan_pass(execution_result, approved, pass_number)
        pass_result["execution_result"] = execution_result
        pass_result["execution_summary"] = deepcopy(_as_dict(execution_result.get("execution_summary")))
        pass_result["execution_summary"]["coverage"] = coverage
        pass_result["evaluation"] = evaluation
        pass_result["result_summary"] = {
            "status": pass_result["execution_summary"].get("status"),
            "ranking_status": evaluation.get("ranking_status"),
            "provider_status": evaluation.get("provider_status"),
            "paper_eligible_count": evaluation.get("paper_eligible_count"),
            "legitimate_ranked_count": evaluation.get("legitimate_ranked_count"),
            "coverage": coverage,
        }
        response["passes"].append(pass_result)

        if evaluation.get("ranking_status") == "unavailable" or evaluation.get("provider_status") == "unavailable":
            stop_reason = "Provider or essential market data unavailable; no retry against the same provider."
            break
        if evaluation.get("paper_eligible_count", 0) > 0:
            stop_reason = "At least one final paper-eligible idea passed strict gates; no further searching."
            break
        if evaluation.get("sufficient_results"):
            stop_reason = "Sufficient legitimate research results found."
            break
        if pass_number >= max_passes:
            stop_reason = "Maximum validated adaptive pass count reached."
            break
        if not evaluation.get("refinement_allowed"):
            stop_reason = "Refinement not allowed by deterministic pass evaluation."
            break

        proposal_result = propose_scan_refinement(
            initial_approved,
            approved,
            evaluation,
            [_pass_summary(item) for item in response["passes"]],
            runtime_context=runtime_context,
            provider=provider,
        )
        pass_result["refinement_proposal"] = proposal_result
        refinement_provider = proposal_result.get("provider") or refinement_provider
        warnings.extend(_as_list(proposal_result.get("warnings")))
        proposal = _as_dict(proposal_result.get("proposal"))
        if proposal.get("action") != "refine":
            stop_reason = proposal.get("reasoning_summary") or "Refinement proposer chose to stop."
            break

        refined_plan, scope_diagnostics = _apply_refinement_proposal(approved, proposal, scope_lock)
        proposal_result["scope_lock"] = scope_diagnostics
        if not scope_diagnostics.get("ok"):
            stop_reason = "Refinement proposal violated scope locks."
            pass_result["warnings"].append(stop_reason)
            break
        refined_validation = validate_scan_plan(refined_plan, runtime_context=runtime_context)
        refined_universe = build_combined_universe(_as_dict(refined_validation.get("execution_config")))
        refined_fingerprint = plan_fingerprint(_as_dict(refined_validation.get("approved_plan")), effective_tickers=_as_list(refined_universe.get("tickers")))
        if refined_fingerprint in seen_fingerprints:
            stop_reason = "Refinement produced an identical plan fingerprint; adaptive loop stopped."
            pass_result["warnings"].append(stop_reason)
            break
        current_plan = refined_plan
        refinement_used = True

    response["passes_executed"] = len([item for item in response["passes"] if item.get("execution_result")])
    response["refinement_used"] = refinement_used
    response["refinement_provider"] = refinement_provider if refinement_used else "none"
    response["stop_reason"] = stop_reason or "Adaptive execution completed."
    if response["passes"]:
        consolidated, best, assistant, research, formatted = _finalize_consolidated_response(
            passes=response["passes"],
            approved_plan=initial_approved,
            execution_config=initial_execution_config,
            runtime_context=runtime_context,
            root_run_id=root_run_id,
            stop_reason=response["stop_reason"],
            refinement_used=refinement_used,
            warnings=warnings,
        )
        response["consolidated_result"] = consolidated
        response["best_available_ideas"] = best
        response["assistant_response"] = assistant
        response["option_discovery"] = _as_dict(consolidated.get("option_discovery"))
        response["research"] = research
        response["formatted_response"] = formatted
        response["assistant_response"].setdefault("scan_summary", {})["active_policy_version"] = response["active_policy_version"]
        response["assistant_response"].setdefault("scan_summary", {})["active_policy_fingerprint"] = response["active_policy_fingerprint"]
    response["warnings"] = _unique_texts(warnings)
    response["errors"] = _unique_texts(errors)
    response["status"] = _status_from_stop(response["stop_reason"], response["passes"], response["errors"])
    response["ok"] = response["status"] in {"completed", "completed_with_warnings", "unavailable"}
    recording = record_adaptive_research_execution(
        response,
        db_path=db_path,
        policy_context={
            "policy_version": response["active_policy_version"],
            "policy_fingerprint": response["active_policy_fingerprint"],
            "policy": active_policy.get("policy"),
        },
    )
    response["learning_recording"] = recording
    if not recording.get("ok"):
        response["warnings"] = _unique_texts(response["warnings"] + list(_as_list(recording.get("warnings"))))
    return response


__all__ = [
    "ADAPTIVE_EXECUTION_VERSION",
    "SCAN_PASS_EVALUATION_VERSION",
    "create_refinement_scope_lock",
    "evaluate_scan_pass",
    "execute_adaptive_scan_plan",
    "plan_fingerprint",
    "propose_scan_refinement",
]
