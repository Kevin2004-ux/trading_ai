from __future__ import annotations

from copy import deepcopy
from importlib.util import find_spec
from typing import Any
import json
import os
import re
import uuid

from pydantic import BaseModel, ConfigDict, Field

from scanner.universe_builder import validate_ticker_universe

from .planner_prompts import build_planner_system_prompt
from .policy_validator import (
    POLICY_LIMITS,
    POLICY_VERSION,
    SUPPORTED_PROFILES,
    SUPPORTED_UNIVERSES,
    validate_scan_plan,
)
from .scan_plan import ScanPlan, build_default_scan_plan, plan_to_dict


AI_PLANNER_VERSION = "ai_scan_planner_v1"
DEFAULT_OPENAI_PLANNER_MODEL = "gpt-4.1-mini"
DEFAULT_OPENAI_PLANNER_TIMEOUT_SECONDS = 20.0

_PROVIDER_CHOICES = {"auto", "openai", "deterministic"}
_NO_OPTIONS_TERMS = (
    "stock only",
    "stocks only",
    "equities only",
    "equity only",
    "do not include options",
    "don't include options",
    "no options",
    "without options",
    "exclude options",
)
_OPTION_TERMS = ("option", "options", "call", "calls", "put", "puts", "spread", "spreads")
_BOTH_TERMS = ("stocks and options", "stock and option", "equities and options", "both stocks and options")
_SYSTEM_TERMS = (
    "system status",
    "status",
    "readiness",
    "diagnostic",
    "diagnostics",
    "what is broken",
    "what's broken",
    "why is tws",
    "why is ibkr",
    "api key",
    "api keys",
    "provider",
)
_PERFORMANCE_TERMS = ("performance", "win rate", "expectancy", "strategy performance")
_OPEN_TRADE_TERMS = ("open trade", "open trades", "current paper trades", "paper portfolio")
_WATCHLIST_TERMS = ("watchlist", "watch list", "watch", "near miss", "near-miss", "blocked but interesting", "blocked-but-interesting")
_EXPLAIN_NO_TRADE_TERMS = ("why no trades", "why nothing passed", "nothing passed", "no final trades", "no trades passed")
_REVIEW_TERMS = ("review", "analyze", "analyse", "look at", "check", "ticker")
_RESEARCH_NEWS_TERMS = ("current news", "check news", "news", "catalyst", "catalysts", "developments")
_RESEARCH_SEC_TERMS = ("filing", "filings", "sec", "10-k", "10-q", "8-k")
_RESEARCH_EARNINGS_TERMS = ("earnings", "transcript", "transcripts", "guidance")
_TECHNICAL_ONLY_TERMS = ("technical only", "technical-only", "technicals only", "no research", "without research")
_TICKER_EXCLUSIONS = {
    "A",
    "AI",
    "API",
    "APIS",
    "BEST",
    "BUY",
    "CALL",
    "CALLS",
    "DO",
    "ETF",
    "FIND",
    "FOR",
    "GIVE",
    "HOW",
    "IBKR",
    "ME",
    "NO",
    "NOT",
    "OPEN",
    "OPTION",
    "OPTIONS",
    "PAPER",
    "PICK",
    "PICKS",
    "PLAN",
    "PUT",
    "PUTS",
    "SCAN",
    "SELL",
    "SHOW",
    "SPREAD",
    "STOCK",
    "STOCKS",
    "SYSTEM",
    "THE",
    "TO",
    "TOP",
    "TRADE",
    "TRADES",
    "TWS",
    "WATCH",
    "WHAT",
    "WHY",
}


class PlannerIntentModel(BaseModel):
    model_config = ConfigDict(extra="allow")

    objective: str = "best_ideas"
    requested_instrument: str = "stocks"
    ticker: str | None = None
    direction: str = "long"
    time_horizon: str = "swing"
    user_requested_execution: bool = False


class PlannerProposalModel(BaseModel):
    model_config = ConfigDict(extra="allow")

    intent: PlannerIntentModel = Field(default_factory=PlannerIntentModel)
    proposed_plan: ScanPlan = Field(default_factory=ScanPlan)
    planner_summary: str = ""


def _as_dict(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list:
    return value if isinstance(value, list) else []


def _dedupe(values: list[Any]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        item = str(value or "").strip()
        key = item.lower()
        if not item or key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def _safe_str(value: Any, limit: int = 260) -> str:
    text = str(value or "").strip()
    if len(text) > limit:
        return f"{text[: limit - 3]}..."
    return text


def _normalize_provider(provider: str | None = None) -> str:
    requested = str(provider or os.getenv("AI_PLANNER_PROVIDER") or "auto").strip().lower()
    return requested if requested in _PROVIDER_CHOICES else "auto"


def _openai_api_key_configured() -> bool:
    return bool(os.getenv("OPENAI_API_KEY"))


def _openai_sdk_available() -> bool:
    return find_spec("openai") is not None


def _planner_model() -> str:
    return str(os.getenv("OPENAI_PLANNER_MODEL") or DEFAULT_OPENAI_PLANNER_MODEL).strip() or DEFAULT_OPENAI_PLANNER_MODEL


def _planner_timeout_seconds() -> float:
    raw = os.getenv("OPENAI_PLANNER_TIMEOUT_SECONDS")
    try:
        value = float(raw) if raw is not None else DEFAULT_OPENAI_PLANNER_TIMEOUT_SECONDS
    except (TypeError, ValueError):
        return DEFAULT_OPENAI_PLANNER_TIMEOUT_SECONDS
    return max(1.0, min(120.0, value))


def get_ai_planner_status(provider: str | None = None) -> dict:
    requested = _normalize_provider(provider)
    sdk_available = _openai_sdk_available()
    configured = _openai_api_key_configured()
    openai_available = sdk_available and configured
    return {
        "ai_planner_provider": requested,
        "openai_planner_configured": configured,
        "openai_planner_sdk_available": sdk_available,
        "openai_planner_model": _planner_model(),
        "ai_planner_available": requested != "deterministic" and openai_available,
    }


def _create_openai_client(api_key: str, timeout: float):
    from openai import OpenAI

    return OpenAI(api_key=api_key, timeout=timeout)


def sanitize_runtime_context(runtime_context: dict | None = None) -> dict:
    context = _as_dict(runtime_context)
    allowed_scalar_keys = (
        "provider_status",
        "market_data_provider_status",
        "market_data_available",
        "safe_to_run_market_data",
        "market_data_ready",
        "safe_to_run_options",
        "options_ready",
        "option_quotes_validated",
        "options_quotes_validated",
        "options_provider_status",
        "market_open",
        "session_state",
        "open_paper_trade_count",
        "paper_trading_only",
    )
    sanitized: dict[str, Any] = {}
    for key in allowed_scalar_keys:
        if key in context and isinstance(context[key], (bool, int, float, str)) and "key" not in key.lower():
            sanitized[key] = context[key]

    market_regime = _as_dict(context.get("market_regime"))
    if market_regime:
        sanitized["market_regime"] = {
            key: market_regime.get(key)
            for key in ("label", "regime", "trend", "risk_level", "volatility_regime")
            if key in market_regime and isinstance(market_regime.get(key), (bool, int, float, str))
        }

    volatility = context.get("volatility_regime")
    if isinstance(volatility, (bool, int, float, str)):
        sanitized["volatility_regime"] = volatility

    sanitized["supported_universes"] = list(SUPPORTED_UNIVERSES)
    sanitized["supported_profiles"] = list(SUPPORTED_PROFILES)
    sanitized["policy_version"] = POLICY_VERSION
    sanitized["policy_limits"] = deepcopy(POLICY_LIMITS)
    sanitized["paper_trading_only"] = True
    return sanitized


def sanitize_user_preferences(user_preferences: dict | None = None) -> dict:
    preferences = _as_dict(user_preferences)
    allowed = (
        "risk_mode",
        "max_tickers",
        "max_candidates",
        "max_final_trades",
        "min_final_trades",
        "requested_instrument",
        "include_options",
        "prefer_options",
        "universes",
        "profiles",
        "tickers",
        "custom_tickers",
        "include_catalysts",
        "include_market_regime",
        "include_relative_strength",
        "include_portfolio_risk",
        "include_position_sizing",
        "research_preferences",
        "refinement",
    )
    sanitized: dict[str, Any] = {}
    for key in allowed:
        if key in preferences:
            value = preferences[key]
            if isinstance(value, (str, int, float, bool)) or value is None:
                sanitized[key] = value
            elif isinstance(value, list):
                sanitized[key] = [item for item in value if isinstance(item, (str, int, float, bool))]
            elif isinstance(value, dict):
                if key == "research_preferences":
                    allowed_research_keys = {"include_news", "include_sec_filings", "include_earnings_transcripts", "include_short_interest"}
                    sanitized[key] = {
                        str(nested_key): bool(nested_value)
                        for nested_key, nested_value in value.items()
                        if str(nested_key) in allowed_research_keys and isinstance(nested_value, (str, int, float, bool))
                    }
                elif key == "refinement":
                    allowed_refinement_keys = {"max_passes", "allow_broader_universe_on_retry", "allow_profile_change_on_retry"}
                    sanitized[key] = {
                        str(nested_key): nested_value
                        for nested_key, nested_value in value.items()
                        if str(nested_key) in allowed_refinement_keys and isinstance(nested_value, (str, int, float, bool))
                    }
                else:
                    sanitized[key] = {
                        str(nested_key): nested_value
                        for nested_key, nested_value in value.items()
                        if isinstance(nested_value, (str, int, float, bool)) and "key" not in str(nested_key).lower()
                    }
    return sanitized


def _message_has_any(message: str, terms: tuple[str, ...]) -> bool:
    normalized = message.lower().replace("-", " ")
    return any(term.replace("-", " ") in normalized for term in terms)


def _stock_only(message: str) -> bool:
    normalized = message.lower().replace("-", " ")
    return any(term.replace("-", " ") in normalized for term in _NO_OPTIONS_TERMS)


def _wants_options(message: str) -> bool:
    if _stock_only(message):
        return False
    return any(term in message.lower() for term in _OPTION_TERMS)


def _explicit_both(message: str) -> bool:
    normalized = message.lower().replace("-", " ")
    return any(term in normalized for term in _BOTH_TERMS)


def _extract_explicit_tickers(message: str) -> list[str]:
    candidates = re.findall(r"(?<![A-Za-z])\$?([A-Z]{1,5}(?:[.-][A-Z])?)(?![A-Za-z])", message or "")
    filtered = []
    for raw in candidates:
        ticker = raw.upper()
        if ticker in _TICKER_EXCLUSIONS:
            continue
        filtered.append(ticker)
    validation = validate_ticker_universe(filtered, max_tickers=10)
    return validation.get("tickers", []) if isinstance(validation, dict) and validation.get("ok") else []


def _enforce_message_boundaries(message: str, proposed_plan: ScanPlan | dict) -> dict:
    plan = proposed_plan.model_dump(mode="python") if isinstance(proposed_plan, ScanPlan) else deepcopy(_as_dict(proposed_plan))
    explicit_tickers = _extract_explicit_tickers(message)
    if _stock_only(message):
        plan["requested_instrument"] = "stocks"
        plan["include_options"] = False
        plan["prefer_options"] = False
    if not explicit_tickers and plan.get("custom_tickers"):
        plan["custom_tickers"] = []
        if plan.get("universes") == ["custom"] or "custom" in _as_list(plan.get("universes")):
            plan["universes"] = ["large_cap"]
    elif explicit_tickers and plan.get("custom_tickers"):
        allowed = set(explicit_tickers)
        plan["custom_tickers"] = [ticker for ticker in _as_list(plan.get("custom_tickers")) if str(ticker).upper() in allowed]
    return plan


def _intent_from_message(message: str, user_preferences: dict | None = None) -> dict:
    preferences = sanitize_user_preferences(user_preferences)
    tickers = _extract_explicit_tickers(message)
    objective = "best_ideas"
    requested_instrument = "stocks"

    if _message_has_any(message, _SYSTEM_TERMS):
        objective = "system_status"
    elif _message_has_any(message, _PERFORMANCE_TERMS):
        objective = "performance"
    elif _message_has_any(message, _OPEN_TRADE_TERMS):
        objective = "open_trades"
    elif tickers and _message_has_any(message, _REVIEW_TERMS):
        objective = "ticker_review"
    elif _message_has_any(message, _WATCHLIST_TERMS):
        objective = "watchlist"
    elif _message_has_any(message, _EXPLAIN_NO_TRADE_TERMS):
        objective = "best_ideas"

    if _explicit_both(message):
        requested_instrument = "both"
    elif _wants_options(message):
        requested_instrument = "options"
    elif _stock_only(message):
        requested_instrument = "stocks"
    elif str(preferences.get("requested_instrument") or "").lower() in {"stocks", "options", "both"}:
        requested_instrument = str(preferences["requested_instrument"]).lower()

    if objective == "system_status":
        requested_instrument = "stocks"

    return {
        "objective": objective,
        "requested_instrument": requested_instrument,
        "ticker": tickers[0] if tickers else None,
        "direction": "long",
        "time_horizon": "swing",
        "explicit_tickers": tickers,
        "research_preferences": _research_preferences_from_message(message),
    }


def _research_preferences_from_message(message: str) -> dict:
    if _message_has_any(message, _TECHNICAL_ONLY_TERMS):
        return {
            "include_news": False,
            "include_sec_filings": False,
            "include_earnings_transcripts": False,
            "include_short_interest": False,
        }
    return {
        "include_news": _message_has_any(message, _RESEARCH_NEWS_TERMS),
        "include_sec_filings": _message_has_any(message, _RESEARCH_SEC_TERMS),
        "include_earnings_transcripts": _message_has_any(message, _RESEARCH_EARNINGS_TERMS),
        "include_short_interest": False,
    }


def _apply_preferences_to_plan(plan: ScanPlan, user_preferences: dict | None = None) -> ScanPlan:
    preferences = sanitize_user_preferences(user_preferences)
    payload = plan.model_dump(mode="python")
    for field in (
        "max_tickers",
        "max_candidates",
        "max_final_trades",
        "min_final_trades",
        "include_catalysts",
        "include_market_regime",
        "include_relative_strength",
        "include_portfolio_risk",
        "include_position_sizing",
    ):
        if field in preferences:
            payload[field] = preferences[field]

    for field in ("universes", "profiles"):
        if field in preferences and isinstance(preferences[field], list):
            payload[field] = preferences[field]
    if "custom_tickers" in preferences and isinstance(preferences["custom_tickers"], list):
        payload["custom_tickers"] = preferences["custom_tickers"]
        payload["universes"] = ["custom"]
    elif "tickers" in preferences and isinstance(preferences["tickers"], list):
        payload["custom_tickers"] = preferences["tickers"]
        payload["universes"] = ["custom"]

    if "include_options" in preferences:
        payload["include_options"] = bool(preferences["include_options"])
    if "prefer_options" in preferences:
        payload["prefer_options"] = bool(preferences["prefer_options"])
    if "research_preferences" in preferences and isinstance(preferences["research_preferences"], dict):
        current = _as_dict(payload.get("research_preferences"))
        current.update(sanitize_user_preferences({"research_preferences": preferences["research_preferences"]}).get("research_preferences", preferences["research_preferences"]))
        payload["research_preferences"] = current
    if "refinement" in preferences and isinstance(preferences["refinement"], dict):
        current = _as_dict(payload.get("refinement"))
        current.update(sanitize_user_preferences({"refinement": preferences["refinement"]}).get("refinement", preferences["refinement"]))
        payload["refinement"] = current

    return ScanPlan.model_validate(payload)


def _deterministic_plan(message: str, request_id: str, user_preferences: dict | None = None) -> tuple[dict, ScanPlan, str]:
    intent = _intent_from_message(message, user_preferences=user_preferences)
    objective = intent["objective"]
    supported_objective = objective if objective in {"best_ideas", "ticker_review", "watchlist", "options_research"} else "best_ideas"
    if intent["requested_instrument"] == "options" and supported_objective == "best_ideas":
        supported_objective = "options_research"

    plan = build_default_scan_plan(
        objective=supported_objective,
        requested_instrument=intent["requested_instrument"],
        ticker=intent.get("ticker"),
    )
    if intent.get("explicit_tickers") and supported_objective != "ticker_review":
        payload = plan.model_dump(mode="python")
        payload["universes"] = ["custom"]
        payload["custom_tickers"] = intent["explicit_tickers"]
        payload["max_tickers"] = len(intent["explicit_tickers"])
        plan = ScanPlan.model_validate(payload)

    plan = _apply_preferences_to_plan(plan, user_preferences=user_preferences)
    payload = plan.model_dump(mode="python")
    research_preferences = _as_dict(payload.get("research_preferences"))
    research_preferences.update(intent.get("research_preferences", {}))
    payload["research_preferences"] = research_preferences
    refinement = _as_dict(payload.get("refinement"))
    try:
        requested_max_passes = int(refinement.get("max_passes") or 1)
    except (TypeError, ValueError):
        requested_max_passes = 1
    if objective in {"best_ideas", "watchlist", "options_research"} and not intent.get("explicit_tickers"):
        refinement["max_passes"] = max(2, requested_max_passes)
    else:
        refinement["max_passes"] = 1
    payload["refinement"] = refinement
    payload["created_by"] = "deterministic_planner"
    payload["request_id"] = request_id
    payload["reasoning_summary"] = _deterministic_summary(intent)
    plan = ScanPlan.model_validate(payload)
    return intent, plan, payload["reasoning_summary"]


def _deterministic_summary(intent: dict) -> str:
    objective = intent.get("objective")
    instrument = intent.get("requested_instrument")
    if objective == "system_status":
        return "System/status request detected; no market scan should run unless explicitly requested."
    if objective == "performance":
        return "Performance request detected; use source-of-truth performance data instead of a market scan when possible."
    if objective == "open_trades":
        return "Open-trades request detected; use source-of-truth trade records instead of a market scan when possible."
    if objective == "ticker_review" and intent.get("ticker"):
        return f"Explicit ticker review requested for {intent['ticker']}."
    if instrument == "options":
        return "Options research requested; final option recommendations remain blocked unless deterministic option quote gates pass."
    if instrument == "both":
        return "Stocks and options requested; deterministic gates decide all eligible and blocked buckets."
    return "Best available stock ideas requested; keep options disabled unless explicitly requested."


def _usage_from_response(response: Any) -> dict:
    usage = getattr(response, "usage", None)
    if usage is None:
        return {}
    if hasattr(usage, "model_dump"):
        return usage.model_dump(mode="json")
    if isinstance(usage, dict):
        return dict(usage)
    result = {}
    for key in ("input_tokens", "output_tokens", "total_tokens"):
        value = getattr(usage, key, None)
        if value is not None:
            result[key] = value
    return result


def _proposal_to_payload(parsed: Any) -> tuple[dict, dict, str]:
    if hasattr(parsed, "model_dump"):
        payload = parsed.model_dump(mode="python")
    elif isinstance(parsed, dict):
        payload = deepcopy(parsed)
    else:
        payload = {}
    intent = _as_dict(payload.get("intent")) or PlannerIntentModel().model_dump(mode="python")
    proposed_plan = payload.get("proposed_plan") or {}
    summary = _safe_str(payload.get("planner_summary") or _as_dict(proposed_plan).get("reasoning_summary"))
    return intent, proposed_plan, summary


def _propose_with_openai(message: str, sanitized_context: dict, sanitized_preferences: dict, request_id: str) -> tuple[dict, dict, str, dict]:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OpenAI planner is not configured.")
    client = _create_openai_client(api_key=api_key, timeout=_planner_timeout_seconds())
    model = _planner_model()
    response = client.responses.parse(
        model=model,
        input=[
            {"role": "system", "content": build_planner_system_prompt()},
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "user_message": _safe_str(message, limit=2000),
                        "request_id": request_id,
                        "runtime_context": sanitized_context,
                        "user_preferences": sanitized_preferences,
                    },
                    sort_keys=True,
                ),
            },
        ],
        text_format=PlannerProposalModel,
    )
    parsed = getattr(response, "output_parsed", None)
    if parsed is None:
        raise RuntimeError("OpenAI planner returned no structured plan.")
    intent, proposed_plan, summary = _proposal_to_payload(parsed)
    return intent, proposed_plan, summary or "OpenAI planner proposed a ScanPlan for deterministic validation.", _usage_from_response(response)


def _base_result(request_id: str, provider: str, model: str | None = None) -> dict:
    return {
        "ok": False,
        "planner_version": AI_PLANNER_VERSION,
        "status": "failed",
        "provider": provider,
        "model": model,
        "ai_available": False,
        "fallback_used": False,
        "request_id": request_id,
        "intent": {},
        "proposed_plan": {},
        "policy_validation": {},
        "approved_plan": {},
        "planner_summary": "",
        "warnings": [],
        "errors": [],
        "usage": {},
    }


def _validated_result(
    *,
    request_id: str,
    provider: str,
    model: str | None,
    status: str,
    ai_available: bool,
    fallback_used: bool,
    intent: dict,
    proposed_plan: ScanPlan | dict,
    planner_summary: str,
    runtime_context: dict,
    warnings: list[str] | None = None,
    errors: list[str] | None = None,
    usage: dict | None = None,
) -> dict:
    result = _base_result(request_id=request_id, provider=provider, model=model)
    try:
        from learning.policy_registry import active_policy_defaults

        active_policy = active_policy_defaults("strategy_library.db")
    except Exception:
        active_policy = {"active_policy_version": None, "active_policy_fingerprint": None}
    proposed_payload = proposed_plan.model_dump(mode="python") if isinstance(proposed_plan, ScanPlan) else deepcopy(_as_dict(proposed_plan))
    if request_id:
        proposed_payload["request_id"] = request_id
    if status == "ai_planned":
        proposed_payload["created_by"] = "openai_planner"
    policy_validation = validate_scan_plan(proposed_payload, runtime_context=runtime_context)
    combined_warnings = _dedupe(list(warnings or []) + list(_as_list(policy_validation.get("warnings"))))
    combined_errors = _dedupe(list(errors or []) + list(_as_list(policy_validation.get("errors"))))
    result.update(
        {
            "ok": bool(policy_validation.get("ok")) and not combined_errors,
            "status": status if bool(policy_validation.get("ok")) and not combined_errors else "validation_failed",
            "ai_available": ai_available,
            "fallback_used": fallback_used,
            "intent": intent,
            "proposed_plan": policy_validation.get("proposed_plan", proposed_payload),
            "policy_validation": policy_validation,
            "approved_plan": policy_validation.get("approved_plan", {}),
            "planner_summary": _safe_str(planner_summary or _as_dict(policy_validation.get("approved_plan")).get("reasoning_summary")),
            "active_policy_version": active_policy.get("active_policy_version"),
            "active_policy_fingerprint": active_policy.get("active_policy_fingerprint"),
            "warnings": combined_warnings,
            "errors": combined_errors,
            "usage": usage or {},
        }
    )
    return result


def _deterministic_result(
    *,
    message: str,
    request_id: str,
    runtime_context: dict,
    user_preferences: dict | None,
    provider: str,
    warnings: list[str] | None = None,
) -> dict:
    intent, plan, summary = _deterministic_plan(message, request_id=request_id, user_preferences=user_preferences)
    return _validated_result(
        request_id=request_id,
        provider=provider,
        model=None,
        status="deterministic_planned",
        ai_available=False,
        fallback_used=provider != "deterministic",
        intent=intent,
        proposed_plan=plan,
        planner_summary=summary,
        runtime_context=runtime_context,
        warnings=warnings or [],
        errors=[],
        usage={},
    )


def propose_scan_plan(
    message: str,
    runtime_context: dict | None = None,
    user_preferences: dict | None = None,
    request_id: str | None = None,
    provider: str | None = None,
) -> dict:
    resolved_request_id = request_id or str(uuid.uuid4())
    selected_provider = _normalize_provider(provider)
    sanitized_context = sanitize_runtime_context(runtime_context)
    sanitized_preferences = sanitize_user_preferences(user_preferences)

    if selected_provider == "deterministic":
        return _deterministic_result(
            message=message,
            request_id=resolved_request_id,
            runtime_context=sanitized_context,
            user_preferences=sanitized_preferences,
            provider="deterministic",
        )

    sdk_available = _openai_sdk_available()
    api_configured = _openai_api_key_configured()
    should_try_openai = selected_provider == "openai" or (selected_provider == "auto" and sdk_available and api_configured)
    if not should_try_openai:
        reasons = []
        if not api_configured:
            reasons.append("OpenAI planner API key is not configured.")
        if not sdk_available:
            reasons.append("OpenAI SDK is not installed.")
        return _deterministic_result(
            message=message,
            request_id=resolved_request_id,
            runtime_context=sanitized_context,
            user_preferences=sanitized_preferences,
            provider=selected_provider,
            warnings=reasons or ["OpenAI planner is unavailable; deterministic planner used."],
        )

    try:
        intent, proposed_plan, summary, usage = _propose_with_openai(
            message=message,
            sanitized_context=sanitized_context,
            sanitized_preferences=sanitized_preferences,
            request_id=resolved_request_id,
        )
        proposed_plan = _enforce_message_boundaries(message, proposed_plan)
        if _stock_only(message):
            intent["requested_instrument"] = "stocks"
        return _validated_result(
            request_id=resolved_request_id,
            provider="openai",
            model=_planner_model(),
            status="ai_planned",
            ai_available=True,
            fallback_used=False,
            intent=intent,
            proposed_plan=proposed_plan,
            planner_summary=summary,
            runtime_context=sanitized_context,
            warnings=[],
            errors=[],
            usage=usage,
        )
    except Exception as exc:
        return _deterministic_result(
            message=message,
            request_id=resolved_request_id,
            runtime_context=sanitized_context,
            user_preferences=sanitized_preferences,
            provider=selected_provider,
            warnings=[f"OpenAI planner unavailable; deterministic fallback used: {_safe_str(exc, limit=160)}"],
        )


__all__ = [
    "AI_PLANNER_VERSION",
    "PlannerIntentModel",
    "PlannerProposalModel",
    "get_ai_planner_status",
    "propose_scan_plan",
    "sanitize_runtime_context",
    "sanitize_user_preferences",
]
