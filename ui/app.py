# ui/app.py

from __future__ import annotations

from typing import Callable
import os
import re
import sys

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

sys.path.append(".")

from alerts.alert_manager import list_alerts  # noqa: E402
from config.runtime_readiness import check_runtime_readiness  # noqa: E402
from config.startup_validator import validate_startup_config  # noqa: E402
from db.audit_log import verify_audit_chain  # noqa: E402
from db.schema_manager import get_schema_version, validate_schema  # noqa: E402
from diagnostics.healthcheck import check_environment  # noqa: E402
from diagnostics.live_dry_run import run_provider_dry_run  # noqa: E402
from agent.trading_brain import (  # noqa: E402
    monitor_open_trades,
    review_ticker_opportunity,
    run_weekly_trade_hunt,
)
from journal.trade_journal import (  # noqa: E402
    get_trade_reviews,
    review_closed_trades,
)
from jobs.job_history import list_job_runs  # noqa: E402
from jobs.job_registry import list_registered_jobs  # noqa: E402
from ideas import build_assistant_trade_response, build_best_available_ideas, format_best_ideas_response  # noqa: E402
from learning import (  # noqa: E402
    create_policy_proposal,
    evaluate_policy_walk_forward,
    get_learning_status,
    grade_mature_candidate_outcomes,
    list_policies,
    promote_policy_proposal,
)
from memory.annotation_store import add_human_annotation  # noqa: E402
from options.strategy_builder import build_option_strategy_candidates  # noqa: E402
from paper.paper_trader import (  # noqa: E402
    get_paper_trading_summary,
    review_paper_portfolio,
    run_paper_trade_cycle,
)
from planning import execute_adaptive_scan_plan, execute_scan_plan, get_ai_planner_status, propose_scan_plan, validate_scan_plan  # noqa: E402
from research import build_current_research, get_research_runtime_status  # noqa: E402
from realtime.market_data import get_market_snapshot  # noqa: E402
from realtime.options_chain import get_options_chain  # noqa: E402
from reports.report_generator import generate_performance_diagnostics_report  # noqa: E402
from scanner.options_discovery import discover_option_ideas  # noqa: E402
from scanner.universe_builder import validate_ticker_universe  # noqa: E402
from simulation.scenario_definitions import list_stress_scenarios  # noqa: E402
from simulation.scenario_runner import run_default_stress_suite  # noqa: E402
from tools.agent_tools import generate_report_tool  # noqa: E402
from tracking.outcome_grader import update_open_recommendations  # noqa: E402
from tracking.trade_logger import (  # noqa: E402
    get_recommendation,
    get_open_recommendations,
    get_strategy_performance,
    get_trade_history,
    get_win_loss_record,
)
from translator.main import ask_translator, get_model_init_error  # noqa: E402
from ui.api_bridge import run_blocking_backend_call  # noqa: E402

DEFAULT_CHAT_SCAN_TIMEOUT_SECONDS = 45.0
CHAT_SCAN_TIMEOUT_WARNING = "Market data provider timed out. IBKR/TWS may be unavailable or blocked by a stale API session."
DEFAULT_CHAT_BROAD_SCAN_MAX_TICKERS = 6
DEFAULT_CHAT_BROAD_SCAN_MAX_CANDIDATES = 6
DEFAULT_CHAT_DISCOVERY_SOURCES = ["manual_hotlist", "database_recent", "liquid_fallback"]


def _load_optional_prediction_dossier() -> tuple[Callable | None, str | None]:
    try:
        from tools.get_prediction_dossier import get_prediction_dossier

        return get_prediction_dossier, None
    except Exception as exc:
        return None, str(exc)


LEGACY_PREDICTION_DOSSIER, LEGACY_PREDICTION_DOSSIER_ERROR = _load_optional_prediction_dossier()

app = FastAPI(title="Trading AI API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


class AskRequest(BaseModel):
    question: str


class ChatRequest(BaseModel):
    message: str
    db_path: str = "strategy_library.db"


class WeeklyTradeHuntRequest(BaseModel):
    universe: str = "large_cap"
    max_tickers: int = 500
    profiles: list[str] | None = None
    max_trades: int = 5
    min_trades: int = 2
    include_catalysts: bool = True
    include_market_regime: bool = True
    include_relative_strength: bool = True
    include_research_briefs: bool = False
    include_options: bool = False
    prefer_options: bool = False
    max_option_contracts_per_trade: int = 3
    include_portfolio_risk: bool = True
    include_position_sizing: bool = True
    include_memory_context: bool = True
    store_memory: bool = False
    account_size: float = 10000.0
    risk_mode: str = "normal"
    auto_log: bool = False
    db_path: str = "strategy_library.db"


class MonitorOpenTradesRequest(BaseModel):
    update_outcomes: bool = True
    db_path: str = "strategy_library.db"


class UpdateOutcomesRequest(BaseModel):
    db_path: str = "strategy_library.db"


class PaperCycleRequest(BaseModel):
    universe: str = "large_cap"
    max_tickers: int = 500
    profiles: list[str] | None = None
    max_trades: int = 5
    min_trades: int = 2
    include_catalysts: bool = True
    include_market_regime: bool = True
    include_relative_strength: bool = True
    include_options: bool = False
    prefer_options: bool = False
    max_option_contracts_per_trade: int = 3
    include_portfolio_risk: bool = True
    include_position_sizing: bool = True
    include_memory_context: bool = True
    store_memory: bool = False
    account_size: float = 10000.0
    risk_mode: str = "normal"
    db_path: str = "strategy_library.db"


class PaperReviewRequest(BaseModel):
    update_outcomes: bool = True
    include_trade_reviews: bool = True
    store_review_memory: bool = False
    db_path: str = "strategy_library.db"


class JournalReviewClosedTradesRequest(BaseModel):
    db_path: str = "strategy_library.db"
    store_memory: bool = False


class ReportGenerateRequest(BaseModel):
    report_type: str
    payload: dict = Field(default_factory=dict)
    format: str = "markdown"
    db_path: str = "strategy_library.db"


class LiveDryRunRequest(BaseModel):
    ticker: str = "AAPL"
    include_market_data: bool = True
    include_news: bool = True
    include_sec_filings: bool = True
    include_earnings_transcripts: bool = True
    include_options: bool = True
    include_memory: bool = False
    db_path: str = "strategy_library.db"


class OptionsStrategiesRequest(BaseModel):
    ticker: str = "AAPL"
    strategy: str | None = None
    include_live_chain: bool = True


class OptionsDiscoverRequest(BaseModel):
    tickers: list[str] = Field(default_factory=list)
    option_preferences: dict = Field(default_factory=dict)
    runtime_context: dict = Field(default_factory=dict)
    stock_candidates: list[dict] = Field(default_factory=list)
    max_underlyings: int = 5
    max_contracts_per_ticker: int = 3


class AnnotationRequest(BaseModel):
    db_path: str = "strategy_library.db"
    entity_type: str = "trade"
    entity_id: str | None = None
    ticker: str | None = None
    setup_type: str | None = None
    annotation_type: str = "human_note"
    rating: int | None = None
    label: str | None = None
    notes: str | None = None
    payload: dict = Field(default_factory=dict)


class PlanningValidateRequest(BaseModel):
    plan: dict = Field(default_factory=dict)
    runtime_context: dict = Field(default_factory=dict)


class PlanningProposeRequest(BaseModel):
    message: str
    runtime_context: dict = Field(default_factory=dict)
    user_preferences: dict = Field(default_factory=dict)
    request_id: str | None = None
    provider: str | None = None


class PlanningExecuteRequest(BaseModel):
    plan: dict = Field(default_factory=dict)
    runtime_context: dict = Field(default_factory=dict)
    db_path: str = "strategy_library.db"


class PlanningExecuteAdaptiveRequest(BaseModel):
    plan: dict = Field(default_factory=dict)
    runtime_context: dict = Field(default_factory=dict)
    message: str | None = None
    provider: str | None = "auto"
    db_path: str = "strategy_library.db"


class CurrentResearchRequest(BaseModel):
    tickers: list[str] = Field(default_factory=list)
    scopes: list[str] | None = None
    provider: str | None = None
    request_id: str | None = None
    as_of: str | None = None


class LearningGradeOutcomesRequest(BaseModel):
    db_path: str = "strategy_library.db"
    as_of: str | None = None
    horizons: list[int] | None = None


class LearningEvaluatePolicyRequest(BaseModel):
    candidate_policy: dict = Field(default_factory=dict)
    baseline_policy_version: str | None = None
    config: dict = Field(default_factory=dict)
    db_path: str = "strategy_library.db"


class LearningProposalRequest(BaseModel):
    proposed_policy: dict = Field(default_factory=dict)
    baseline_policy_version: str | None = None
    created_by: str = "user"
    db_path: str = "strategy_library.db"


class LearningPromoteRequest(BaseModel):
    proposal_id: int
    approved_by: str
    approval_reason: str
    expected_current_policy_version: str
    confirm: bool = False
    db_path: str = "strategy_library.db"


def _error_response(message: str, status_code: int = 500) -> JSONResponse:
    return JSONResponse(status_code=status_code, content={"ok": False, "error": message})


def _as_dict(value):
    return value if isinstance(value, dict) else {}


def _extract_error(result: dict, fallback: str) -> str:
    if isinstance(result, dict):
        errors = result.get("errors")
        if isinstance(errors, list) and errors:
            return str(errors[0])
        error = result.get("error")
        if error:
            return str(error)
        summary = result.get("summary")
        if isinstance(summary, dict) and summary.get("message"):
            return str(summary["message"])
        message = result.get("message")
        if message:
            return str(message)
    return fallback


def _is_gemini_dead_end(answer: str) -> bool:
    normalized = str(answer or "").lower()
    return (
        "translator is unavailable" in normalized
        or "gemini runtime is not fully configured" in normalized
        or "error occurred while contacting the ai" in normalized
    )


_CHAT_TICKER_EXCLUSIONS = {
    "AI",
    "API",
    "BEST",
    "BUY",
    "CALL",
    "CALLS",
    "DO",
    "FIND",
    "GIVE",
    "IBKR",
    "NO",
    "NOT",
    "OPTION",
    "OPTIONS",
    "PAPER",
    "PLAN",
    "PUT",
    "PUTS",
    "REVIEW",
    "SCAN",
    "SELL",
    "SHOW",
    "STOCK",
    "STOCKS",
    "SYSTEM",
    "TOP",
    "TRADE",
    "TRADES",
    "TWS",
    "WATCH",
    "WHAT",
    "WHY",
}


def _has_explicit_ticker_review(message: str) -> bool:
    normalized = str(message or "").lower()
    if not any(term in normalized for term in ("review", "analyze", "analyse", "check", "look at")):
        return False
    tickers = re.findall(r"(?<![A-Za-z])\$?([A-Z]{1,5}(?:[.-][A-Z])?)(?![A-Za-z])", str(message or ""))
    return any(ticker.upper() not in _CHAT_TICKER_EXCLUSIONS for ticker in tickers)


def _is_trade_question(message: str) -> bool:
    normalized = str(message or "").lower()
    normalized_compact = normalized.replace("-", " ")
    terms = (
        "best available",
        "best available stock",
        "best available stocks",
        "best stock",
        "best stocks",
        "best stock ideas",
        "stock idea",
        "stock ideas",
        "stocks to watch",
        "watchlist idea",
        "watchlist ideas",
        "blocked but interesting",
        "best option",
        "best options",
        "top stock",
        "top stock ideas",
        "top pick",
        "top picks",
        "trade idea",
        "trade ideas",
        "what should i watch",
        "review market",
        "best trade",
        "best trades",
        "find",
        "scan",
        "setup",
        "recommend",
        "opportunity",
        "weekly",
    )
    return any(term in normalized_compact for term in terms) or _has_explicit_ticker_review(message)


def _is_stock_only_request(message: str) -> bool:
    normalized = str(message or "").lower()
    normalized_compact = normalized.replace("-", " ")
    stock_terms = (
        "stock only",
        "stocks only",
        "equities only",
        "equity only",
        "stock idea",
        "stock ideas",
        "stocks to watch",
        "best available stock",
        "best stocks",
        "best stock",
        "top stock",
    )
    no_option_terms = (
        "do not include options",
        "don't include options",
        "no options",
        "without options",
        "exclude options",
    )
    return any(term in normalized_compact for term in stock_terms) or any(term in normalized for term in no_option_terms)


def _wants_options_request(message: str) -> bool:
    normalized = str(message or "").lower()
    if _is_stock_only_request(message):
        return False
    option_terms = ("option", "options", "calls", "puts", "spread", "spreads")
    return any(term in normalized for term in option_terms)


def _is_system_question(message: str) -> bool:
    normalized = str(message or "").lower().replace("-", " ")
    terms = (
        "system status",
        "status",
        "readiness",
        "diagnostic",
        "diagnostics",
        "what is broken",
        "what's broken",
        "provider status",
        "api key",
        "api keys",
    )
    return any(term in normalized for term in terms)


def _is_performance_question(message: str) -> bool:
    normalized = str(message or "").lower()
    terms = ("performance", "win rate", "expectancy", "strategy performance")
    return any(term in normalized for term in terms)


def _is_open_trades_question(message: str) -> bool:
    normalized = str(message or "").lower()
    terms = ("open trade", "open trades", "current paper trades", "paper portfolio")
    return any(term in normalized for term in terms)


def _sanitize_runtime_reason(reason: str | None) -> str | None:
    if not reason:
        return None
    normalized = str(reason)
    if "GEMINI_API_KEY" in normalized:
        return "Gemini API key is not configured."
    return normalized


def _deterministic_chat_fallback(message: str, reason: str | None = None) -> dict:
    safe_reason = _sanitize_runtime_reason(reason)
    if _is_trade_question(message):
        answer = (
            "Gemini is unavailable, so I am using deterministic fallback mode. "
            "For trade ideas, run the Scan page or POST /api/scan; the backend will use objective "
            "paper-trading gates, rank only passing candidates, and keep Gemini out of the decision."
        )
        suggested_action = {
            "label": "Run deterministic scan",
            "endpoint": "/api/scan",
            "method": "POST",
        }
    else:
        answer = (
            "Gemini is unavailable, but the deterministic backend is still online. "
            "Use the Scan, Trades, Performance, Reports, Options, and System pages for source-of-truth "
            "paper-trading data and diagnostics."
        )
        suggested_action = {
            "label": "Open system diagnostics",
            "endpoint": "/api/status",
            "method": "GET",
        }

    warnings = [
        "Gemini is unavailable; deterministic fallback mode is active.",
        "The deterministic backend remains the source of truth.",
        "No failed/watchlist candidate can be upgraded by chat narrative.",
    ]
    if safe_reason:
        warnings.append(f"Gemini status: {safe_reason}")

    return {
        "ok": True,
        "mode": "deterministic_fallback",
        "answer": answer,
        "gemini_available": False,
        "paper_trading_only": True,
        "brokerage_execution_enabled": False,
        "validation": {
            "validation_status": "deterministic_fallback",
            "safe_to_show_user": True,
            "deterministic_engine_source_of_truth": True,
            "deterministic_fallback_used": True,
        },
        "suggested_action": suggested_action,
        "raw_result": {"message": message, "fallback_reason": safe_reason},
        "warnings": warnings,
        "errors": [],
    }


def _requested_instrument_from_message(message: str) -> str:
    if _is_stock_only_request(message):
        return "stocks"
    if _wants_options_request(message):
        return "options"
    return "auto"


def _requested_instrument_from_options(include_options: bool) -> str:
    return "both" if include_options else "stocks"


def _safe_timeout_env(name: str, default: float, minimum: float = 0.01, maximum: float = 300.0) -> float:
    try:
        value = float(os.getenv(name, default))
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(value, maximum))


def _safe_int_env(name: str, default: int, minimum: int = 1, maximum: int = 500) -> int:
    try:
        value = int(os.getenv(name, default))
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(value, maximum))


def _chat_scan_timeout_seconds() -> float:
    return _safe_timeout_env("CHAT_SCAN_TIMEOUT_SECONDS", DEFAULT_CHAT_SCAN_TIMEOUT_SECONDS)


def _planning_execution_timeout_seconds() -> float:
    return _safe_timeout_env("PLANNING_EXECUTION_TIMEOUT_SECONDS", max(DEFAULT_CHAT_SCAN_TIMEOUT_SECONDS, 60.0))


def _chat_broad_scan_max_tickers() -> int:
    return _safe_int_env("CHAT_BROAD_SCAN_MAX_TICKERS", DEFAULT_CHAT_BROAD_SCAN_MAX_TICKERS, minimum=1, maximum=100)


def _chat_broad_scan_max_candidates() -> int:
    return _safe_int_env("CHAT_BROAD_SCAN_MAX_CANDIDATES", DEFAULT_CHAT_BROAD_SCAN_MAX_CANDIDATES, minimum=1, maximum=50)


def _bounded_plan_count(value: object, cap: int) -> int:
    try:
        numeric = int(value) if value not in (None, "") else cap
    except (TypeError, ValueError):
        numeric = cap
    return max(1, min(numeric, cap))


def _chat_scan_internal_controls(timeout_seconds: float, *, broad_scan: bool = False) -> dict:
    default_total_timeout = (
        min(timeout_seconds * 0.2, max(0.01, timeout_seconds - 14.0))
        if broad_scan
        else min(timeout_seconds * 0.55, max(0.01, timeout_seconds - 8.0))
    )
    max_total_timeout = max(0.01, timeout_seconds * 0.95)
    scan_total_timeout = _safe_timeout_env(
        "CHAT_SCAN_TOTAL_TIMEOUT_SECONDS",
        max(0.01, default_total_timeout),
        minimum=0.01,
        maximum=max_total_timeout,
    )
    default_ticker_timeout = min(4.0, scan_total_timeout) if broad_scan else min(8.0, scan_total_timeout / 4.0)
    ticker_timeout = _safe_timeout_env(
        "CHAT_SCAN_TICKER_TIMEOUT_SECONDS",
        max(0.01, default_ticker_timeout),
        minimum=0.01,
        maximum=scan_total_timeout,
    )
    controls = {
        "scan_total_timeout_seconds": scan_total_timeout,
        "scan_ticker_timeout_seconds": ticker_timeout,
    }
    if broad_scan:
        controls.update(
            {
                "chat_broad_scan": True,
                "bounded_first_batch": True,
                "stop_after_first_legitimate_pass": True,
                "use_dynamic_discovery": True,
                "max_discovered_tickers": _chat_broad_scan_max_tickers(),
                "discovery_sources": DEFAULT_CHAT_DISCOVERY_SOURCES,
            }
        )
    return controls


def _safe_max_passes(plan: dict) -> int:
    try:
        return int((plan.get("refinement") or {}).get("max_passes") or 1)
    except (TypeError, ValueError):
        return 1


def _broad_trade_idea_plan(plan: dict) -> bool:
    objective = str(plan.get("objective") or "best_ideas").lower()
    return objective in {"best_ideas", "watchlist", "options_research"} and not bool(plan.get("custom_tickers"))


def _prepare_chat_execution_plan(message: str, approved_plan: dict) -> dict:
    plan = dict(approved_plan or {})
    if _broad_trade_idea_plan(plan):
        plan["max_tickers"] = _bounded_plan_count(plan.get("max_tickers"), _chat_broad_scan_max_tickers())
        plan["max_candidates"] = _bounded_plan_count(plan.get("max_candidates"), _chat_broad_scan_max_candidates())
        refinement = dict(plan.get("refinement") or {})
        refinement["max_passes"] = max(2, _safe_max_passes(plan))
        plan["refinement"] = refinement
    if _is_stock_only_request(message):
        plan["requested_instrument"] = "stocks"
        plan["include_options"] = False
        plan["prefer_options"] = False
    return plan


def _should_use_adaptive_chat_execution(plan: dict) -> bool:
    return _broad_trade_idea_plan(plan) and _safe_max_passes(plan) > 1


def _include_options_from_execution_result(result: dict) -> bool:
    if not isinstance(result, dict):
        return False
    config = _as_dict(result.get("execution_config"))
    if config:
        return bool(config.get("include_options"))
    initial_validation = _as_dict(result.get("initial_policy_validation"))
    initial_config = _as_dict(initial_validation.get("execution_config"))
    if initial_config:
        return bool(initial_config.get("include_options"))
    approved = _as_dict(result.get("approved_plan") or initial_validation.get("approved_plan"))
    return bool(approved.get("include_options"))


def _enrich_with_best_ideas(result: dict, include_options: bool = True, requested_instrument: str | None = None) -> dict:
    if not isinstance(result, dict):
        return result
    enriched = dict(result)
    best_ideas = build_best_available_ideas(enriched, config={"include_options": include_options})
    assistant_response = build_assistant_trade_response(
        best_ideas,
        trading_result=enriched,
        requested_instrument=requested_instrument or _requested_instrument_from_options(include_options),
    )
    enriched["best_available_ideas"] = best_ideas
    enriched["assistant_response"] = assistant_response
    enriched["formatted_best_ideas_summary"] = format_best_ideas_response(assistant_response)
    return enriched


def _run_paper_cycle_payload(request: PaperCycleRequest) -> dict:
    result = run_paper_trade_cycle(
        universe=request.universe,
        max_tickers=request.max_tickers,
        profiles=request.profiles,
        max_trades=request.max_trades,
        min_trades=request.min_trades,
        include_catalysts=request.include_catalysts,
        include_market_regime=request.include_market_regime,
        include_relative_strength=request.include_relative_strength,
        include_options=request.include_options,
        prefer_options=request.prefer_options,
        max_option_contracts_per_trade=request.max_option_contracts_per_trade,
        include_portfolio_risk=request.include_portfolio_risk,
        include_position_sizing=request.include_position_sizing,
        include_memory_context=request.include_memory_context,
        store_memory=request.store_memory,
        account_size=request.account_size,
        risk_mode=request.risk_mode,
        db_path=request.db_path,
    )
    return _enrich_with_best_ideas(
        result,
        include_options=request.include_options,
        requested_instrument=_requested_instrument_from_options(request.include_options),
    )


def _timeout_issue_list(extra: str | None = None) -> list[str]:
    issues = [CHAT_SCAN_TIMEOUT_WARNING]
    if extra:
        issues.append(str(extra))
    return list(dict.fromkeys(item for item in issues if item))


def _chat_scan_timeout_payload(message: str, timeout_seconds: float, bridge_result: dict | None = None) -> dict:
    init_error = get_model_init_error()
    bridge_error = bridge_result.get("error") if isinstance(bridge_result, dict) else None
    system_issues = _timeout_issue_list(bridge_error)
    data_missing = ["Usable market data was not returned before the chat scan timeout."]
    why_no_final_trades = ["The deterministic scan timed out before provider data could be validated."]
    next_steps = [
        "Check that TWS/IBKR is open, read-only API access is enabled, and no stale API session is holding the client ID.",
        "Rerun the request after the market-data provider responds cleanly.",
    ]
    best_ideas = {
        "ok": True,
        "paper_trading_only": True,
        "summary": CHAT_SCAN_TIMEOUT_WARNING,
        "ranking_status": "unavailable",
        "paper_eligible": [],
        "stock_watchlist": [],
        "option_research_only": [],
        "option_underlying_watchlist": [],
        "blocked_but_interesting": [],
        "why_no_final_trades": why_no_final_trades,
        "data_missing": data_missing,
        "system_issues": system_issues,
        "next_steps": next_steps,
        "warnings": system_issues,
    }
    assistant_response = {
        "ok": True,
        "response_type": "trade_ideas",
        "status": "ranking_unavailable",
        "ranking_status": "unavailable",
        "paper_trading_only": True,
        "brokerage_execution_enabled": False,
        "paper_eligible": [],
        "top_stocks": [],
        "top_options": [],
        "option_underlying_watchlist": [],
        "blocked": [],
        "ticker_cards": [],
        "why_no_final_trades": why_no_final_trades,
        "data_missing": data_missing,
        "system_issues": system_issues,
        "next_steps": next_steps,
        "market_state": {
            "provider_status": "unavailable",
            "ranking_status": "unavailable",
            "timeout_seconds": timeout_seconds,
        },
        "scan_summary": {
            "status": "timeout",
            "ranking_status": "unavailable",
            "selected_count": 0,
            "logged_count": 0,
            "auto_log": False,
            "timeout_seconds": timeout_seconds,
        },
        "warnings": system_issues,
        "errors": [],
    }
    answer = format_best_ideas_response(assistant_response)
    scan_result = {
        "ok": False,
        "status": "timeout",
        "ranking_status": "unavailable",
        "paper_trading_only": True,
        "brokerage_execution_enabled": False,
        "error": CHAT_SCAN_TIMEOUT_WARNING,
        "warnings": system_issues,
        "errors": [],
    }
    return {
        "ok": True,
        "mode": "deterministic_timeout",
        "ranking_status": "ranking_unavailable",
        "answer": answer,
        "gemini_available": init_error is None,
        "paper_trading_only": True,
        "brokerage_execution_enabled": False,
        "best_available_ideas": best_ideas,
        "assistant_response": assistant_response,
        "scan_result": scan_result,
        "trading_result": {},
        "formatted_best_ideas_summary": answer,
        "planner": {},
        "planner_provider": None,
        "planner_status": "timeout",
        "planner_fallback_used": init_error is not None,
        "policy_validation": {},
        "approved_plan": {},
        "execution_summary": scan_result,
        "adaptive_execution": None,
        "refinement_used": False,
        "passes_executed": 0,
        "refinement_stop_reason": "Chat scan timeout.",
        "validation": {
            "validation_status": "ranking_unavailable",
            "safe_to_show_user": True,
            "deterministic_engine_source_of_truth": True,
            "deterministic_fallback_used": init_error is not None,
            "timeout": True,
            "paper_trade_logged": False,
        },
        "raw_result": {
            "message": message,
            "timeout_seconds": timeout_seconds,
            "gemini_status": "available" if init_error is None else "unavailable",
            "include_options": _wants_options_request(message) and not _is_stock_only_request(message),
        },
        "warnings": system_issues,
        "errors": [],
    }


def _is_backend_timeout(result: dict) -> bool:
    return isinstance(result, dict) and result.get("source") == "api_bridge" and result.get("error_type") == "TimeoutError"


def _run_best_ideas_chat_scan(message: str, db_path: str, timeout_seconds: float | None = None) -> dict:
    user_preferences = {
        "requested_instrument": _requested_instrument_from_message(message),
        "include_options": _wants_options_request(message),
        "prefer_options": _wants_options_request(message),
    }
    if user_preferences["requested_instrument"] == "auto":
        user_preferences["requested_instrument"] = "options" if _wants_options_request(message) else "stocks"
    if _is_stock_only_request(message):
        user_preferences["requested_instrument"] = "stocks"
        user_preferences["include_options"] = False
        user_preferences["prefer_options"] = False

    planner_result = propose_scan_plan(
        message,
        runtime_context={},
        user_preferences=user_preferences,
    )
    approved_plan = planner_result.get("approved_plan", {}) if isinstance(planner_result, dict) else {}
    execution_plan = _prepare_chat_execution_plan(message, approved_plan)
    use_adaptive = _should_use_adaptive_chat_execution(execution_plan)
    internal_controls = _chat_scan_internal_controls(
        timeout_seconds or _chat_scan_timeout_seconds(),
        broad_scan=_broad_trade_idea_plan(execution_plan),
    )
    execution_result = (
        execute_adaptive_scan_plan(execution_plan, runtime_context={}, db_path=db_path, message=message, internal_controls=internal_controls)
        if use_adaptive
        else execute_scan_plan(execution_plan, runtime_context={}, db_path=db_path, internal_controls=internal_controls)
    )
    best_ideas = execution_result.get("best_available_ideas") if isinstance(execution_result, dict) else {}
    assistant_response = execution_result.get("assistant_response") if isinstance(execution_result, dict) else {}
    discovery_result = execution_result.get("discovery_result") if isinstance(execution_result, dict) else {}
    trading_result = (
        execution_result.get("consolidated_result", {})
        if use_adaptive and isinstance(execution_result, dict)
        else execution_result.get("trading_result", {}) if isinstance(execution_result, dict) else {}
    )
    return {
        "planner": planner_result,
        "scan_result": execution_result,
        "trading_result": trading_result,
        "discovery_result": discovery_result,
        "best_available_ideas": best_ideas,
        "assistant_response": assistant_response,
        "formatted_best_ideas_summary": execution_result.get("formatted_response") or format_best_ideas_response(assistant_response),
        "include_options": _include_options_from_execution_result(execution_result),
        "policy_validation": (
            execution_result.get("initial_policy_validation", {})
            if use_adaptive and isinstance(execution_result, dict)
            else execution_result.get("policy_validation", {}) if isinstance(execution_result, dict) else {}
        ),
        "approved_plan": (
            _as_dict(_as_dict(execution_result.get("initial_policy_validation")).get("approved_plan"))
            if use_adaptive and isinstance(execution_result, dict)
            else execution_result.get("approved_plan", {}) if isinstance(execution_result, dict) else {}
        ),
        "execution_summary": (
            {
                "status": execution_result.get("status"),
                "adaptive_execution_version": execution_result.get("adaptive_execution_version"),
                "passes_executed": execution_result.get("passes_executed"),
                "stop_reason": execution_result.get("stop_reason"),
                "refinement_used": execution_result.get("refinement_used"),
                "discovery_result": discovery_result,
            }
            if use_adaptive and isinstance(execution_result, dict)
            else execution_result.get("execution_summary", {}) if isinstance(execution_result, dict) else {}
        ),
        "adaptive_execution": execution_result if use_adaptive and isinstance(execution_result, dict) else None,
        "refinement_used": bool(execution_result.get("refinement_used")) if use_adaptive and isinstance(execution_result, dict) else False,
        "passes_executed": int(execution_result.get("passes_executed") or 1) if use_adaptive and isinstance(execution_result, dict) else 1,
        "refinement_stop_reason": str(execution_result.get("stop_reason") or "") if use_adaptive and isinstance(execution_result, dict) else "",
    }


def _chat_payload(message: str, db_path: str = "strategy_library.db") -> dict:
    init_error = get_model_init_error()
    if _is_system_question(message):
        status_payload = _status_payload(db_path=db_path)
        return {
            "ok": True,
            "mode": "deterministic_status",
            "answer": "System status is available from the deterministic backend. No market scan was run.",
            "gemini_available": init_error is None,
            "paper_trading_only": True,
            "brokerage_execution_enabled": False,
            "status_payload": status_payload,
            "validation": {
                "validation_status": "source_of_truth_status",
                "safe_to_show_user": True,
                "deterministic_engine_source_of_truth": True,
                "deterministic_fallback_used": init_error is not None,
            },
            "raw_result": {"message": message, "status": status_payload},
            "warnings": list(status_payload.get("warnings", [])),
            "errors": list(status_payload.get("errors", [])),
        }
    if _is_performance_question(message):
        performance_payload = _performance_payload(db_path=db_path)
        return {
            "ok": True,
            "mode": "deterministic_performance",
            "answer": "Performance data is loaded from SQLite source-of-truth records. No market scan was run.",
            "gemini_available": init_error is None,
            "paper_trading_only": True,
            "brokerage_execution_enabled": False,
            "performance": performance_payload,
            "validation": {
                "validation_status": "source_of_truth_performance",
                "safe_to_show_user": True,
                "deterministic_engine_source_of_truth": True,
                "deterministic_fallback_used": init_error is not None,
            },
            "raw_result": {"message": message, "performance": performance_payload},
            "warnings": [],
            "errors": list(performance_payload.get("errors", [])),
        }
    if _is_open_trades_question(message):
        open_trades = get_open_recommendations(db_path=db_path)
        return {
            "ok": True,
            "mode": "deterministic_open_trades",
            "answer": "Open trades are loaded from SQLite source-of-truth records. No market scan was run.",
            "gemini_available": init_error is None,
            "paper_trading_only": True,
            "brokerage_execution_enabled": False,
            "open_recommendations": open_trades,
            "validation": {
                "validation_status": "source_of_truth_open_trades",
                "safe_to_show_user": True,
                "deterministic_engine_source_of_truth": True,
                "deterministic_fallback_used": init_error is not None,
            },
            "raw_result": {"message": message, "open_recommendations": open_trades},
            "warnings": [],
            "errors": [],
        }
    if _is_trade_question(message):
        chat_timeout = _chat_scan_timeout_seconds()
        best_ideas_payload = _run_best_ideas_chat_scan(message, db_path=db_path, timeout_seconds=chat_timeout)
        planner_result = best_ideas_payload.get("planner", {})
        best_ideas = best_ideas_payload["best_available_ideas"]
        assistant_response = best_ideas_payload["assistant_response"]
        answer = best_ideas_payload["formatted_best_ideas_summary"]
        planner_status = str(planner_result.get("status") or "")
        mode = "ai_planned_scan" if planner_status == "ai_planned" else "deterministic_fallback" if init_error else "deterministic_scan"
        warnings = list(best_ideas.get("warnings", [])) + list(planner_result.get("warnings", []))
        if init_error:
            warnings.append("Gemini is unavailable; deterministic scan and formatter were used.")
        else:
            warnings.append("Deterministic scan ran first; Gemini did not override the buckets.")
        return {
            "ok": True,
            "mode": mode,
            "answer": answer,
            "gemini_available": init_error is None,
            "paper_trading_only": True,
            "brokerage_execution_enabled": False,
            "best_available_ideas": best_ideas,
            "assistant_response": assistant_response,
            "scan_result": best_ideas_payload["scan_result"],
            "trading_result": best_ideas_payload["trading_result"],
            "discovery_result": best_ideas_payload.get("discovery_result", {}),
            "formatted_best_ideas_summary": answer,
            "planner": planner_result,
            "planner_provider": planner_result.get("provider"),
            "planner_status": planner_result.get("status"),
            "planner_fallback_used": bool(planner_result.get("fallback_used")),
            "policy_validation": best_ideas_payload["policy_validation"],
            "approved_plan": best_ideas_payload["approved_plan"],
            "execution_summary": best_ideas_payload["execution_summary"],
            "adaptive_execution": best_ideas_payload.get("adaptive_execution"),
            "refinement_used": bool(best_ideas_payload.get("refinement_used")),
            "passes_executed": int(best_ideas_payload.get("passes_executed") or 1),
            "refinement_stop_reason": best_ideas_payload.get("refinement_stop_reason") or "",
            "validation": {
                "validation_status": mode,
                "safe_to_show_user": True,
                "deterministic_engine_source_of_truth": True,
                "deterministic_fallback_used": init_error is not None,
                "planner_fallback_used": bool(planner_result.get("fallback_used")),
                "adaptive_execution_used": bool(best_ideas_payload.get("adaptive_execution")),
            },
            "raw_result": {
                "message": message,
                "gemini_status": "available" if init_error is None else "unavailable",
                "include_options": best_ideas_payload["include_options"],
                "planner_status": planner_result.get("status"),
                "planner_provider": planner_result.get("provider"),
                "approved_plan": best_ideas_payload["approved_plan"],
                "execution_summary": best_ideas_payload["execution_summary"],
                "discovery_result": best_ideas_payload.get("discovery_result", {}),
                "refinement_used": bool(best_ideas_payload.get("refinement_used")),
                "passes_executed": int(best_ideas_payload.get("passes_executed") or 1),
                "refinement_stop_reason": best_ideas_payload.get("refinement_stop_reason") or "",
            },
            "warnings": list(dict.fromkeys(str(item) for item in warnings if item)),
            "errors": list(planner_result.get("errors", [])),
        }

    answer = ask_translator(message)
    if _is_gemini_dead_end(answer):
        return _deterministic_chat_fallback(message, reason=init_error or answer)

    return {
        "ok": True,
        "mode": "gemini",
        "answer": answer,
        "gemini_available": init_error is None,
        "paper_trading_only": True,
        "brokerage_execution_enabled": False,
        "validation": {
            "validation_status": "not_applicable",
            "safe_to_show_user": True,
            "deterministic_engine_source_of_truth": True,
        },
        "raw_result": {"answer": answer, "message": message},
        "warnings": [
            "Gemini cannot override deterministic engine output.",
            "Final trade decisions must come from deterministic scan/logging routes.",
        ],
        "errors": [],
    }


def _status_payload(db_path: str = "strategy_library.db") -> dict:
    readiness = check_runtime_readiness({"DATABASE_PATH": db_path}, include_live_checks=False)
    paper = get_paper_trading_summary(db_path=db_path)
    alerts = list_alerts(db_path=db_path, limit=20)
    validation = validate_schema(db_path=db_path)
    gemini_error = get_model_init_error()
    performance = {
        "win_loss_record": get_win_loss_record(db_path=db_path),
        "strategy_performance": get_strategy_performance(db_path=db_path),
    }
    planner_status = get_ai_planner_status()
    research_status = get_research_runtime_status()
    learning_status = get_learning_status(db_path=db_path)
    return {
        "ok": True,
        "backend": "running",
        "service": "trading_ai",
        "paper_trading_only": True,
        "brokerage_execution_enabled": False,
        "gemini_available": gemini_error is None,
        "gemini_status": "available" if gemini_error is None else "unavailable",
        **planner_status,
        **research_status,
        "ibkr_configured": bool(os.getenv("IBKR_HOST") and os.getenv("IBKR_PORT")),
        "database_ready": bool(validation.get("ok")),
        "frontend_bridge": "ready",
        "readiness": readiness,
        "paper_summary": paper,
        "performance": performance,
        "learning": learning_status,
        "alerts": alerts,
        "warnings": list(readiness.get("warnings", [])) if isinstance(readiness, dict) else [],
        "errors": [],
    }


def _frontend_debug_payload(db_path: str = "strategy_library.db") -> dict:
    gemini_error = get_model_init_error()
    route_paths = sorted(getattr(route, "path", "") for route in app.routes)
    return {
        "ok": True,
        "frontend_bridge": "ready",
        "api_base_url_hint": "Set NEXT_PUBLIC_API_BASE_URL in the frontend environment.",
        "routes": {
            "count": len(route_paths),
            "api_routes": [path for path in route_paths if path.startswith("/api/")],
        },
        "gemini_configured": bool(os.getenv("GEMINI_API_KEY")),
        "gemini_available": gemini_error is None,
        "gemini_status": "available" if gemini_error is None else "unavailable",
        "database_path": db_path,
        "runtime_mode": "paper_trading",
        "paper_trading_only": True,
        "brokerage_execution_enabled": False,
        "known_warnings": [
            "Missing optional API keys should appear as warnings, not startup failures.",
            "IBKR checks require TWS to be open and remain read-only.",
            "Options can be displayed as blocked/research-only when quote permissions are unavailable.",
        ],
        "secrets_exposed": False,
    }


def _db_status_payload(db_path: str = "strategy_library.db") -> dict:
    schema = get_schema_version(db_path=db_path)
    validation = validate_schema(db_path=db_path)
    audit = verify_audit_chain(db_path=db_path)
    return {
        "ok": bool(validation.get("ok")) and bool(audit.get("ok")),
        "db_path": db_path,
        "schema_version": schema,
        "validation": validation,
        "audit_chain": audit,
        "errors": list(validation.get("errors", [])) + list(audit.get("errors", [])),
    }


def _performance_payload(db_path: str = "strategy_library.db") -> dict:
    return {
        "ok": True,
        "win_loss_record": get_win_loss_record(db_path=db_path),
        "strategy_performance": get_strategy_performance(db_path=db_path),
        "diagnostics": generate_performance_diagnostics_report(db_path=db_path, format="dict"),
        "paper_trading_only": True,
        "errors": [],
    }


def _options_strategies_payload(request: OptionsStrategiesRequest) -> dict:
    ticker = str(request.ticker or "AAPL").upper()
    market_snapshot = get_market_snapshot(ticker, lookback_days=180)
    technical = ((market_snapshot.get("data") or {}).get("technical_snapshot") if isinstance(market_snapshot, dict) else {}) or {}
    underlying_view = {
        "ticker": ticker,
        "current_price": technical.get("current_price"),
        "option_bias": "bullish",
        "technical_snapshot": technical,
        "market_snapshot": market_snapshot,
    }
    chain_result = (
        get_options_chain(ticker)
        if request.include_live_chain
        else {"ok": False, "data": {"contracts": []}, "error": "Live option-chain request disabled."}
    )
    contracts = ((chain_result.get("data") or {}).get("contracts") if isinstance(chain_result, dict) else None) or []
    strategies = build_option_strategy_candidates(ticker, underlying_view, contracts)
    if request.strategy:
        requested = str(request.strategy).strip().lower()
        matching = [
            item for item in strategies.get("strategies", [])
            if str(item.get("strategy_type", "")).lower() == requested
        ]
        strategies["requested_strategy"] = requested
        strategies["matching_strategies"] = matching

    warnings = list(strategies.get("warnings", []))
    if not chain_result.get("ok"):
        warnings.append(chain_result.get("error", "Option chain unavailable."))

    return {
        "ok": bool(strategies.get("ok")),
        "ticker": ticker,
        "paper_trading_only": True,
        "brokerage_execution_enabled": False,
        "options_research_only_note": "Blocked/research-only options are not recommendations.",
        "market_snapshot": market_snapshot,
        "options_chain": chain_result,
        "strategy_result": strategies,
        "warnings": warnings,
        "errors": list(strategies.get("errors", [])),
    }


def _options_discover_payload(request: OptionsDiscoverRequest) -> dict:
    validation = validate_ticker_universe(request.tickers, max_tickers=max(1, request.max_underlyings))
    if not validation.get("ok"):
        return {
            "ok": False,
            "paper_trading_only": True,
            "brokerage_execution_enabled": False,
            "error": "; ".join(validation.get("errors", [])) or "No valid option tickers were provided.",
            "errors": validation.get("errors", []),
        }
    result = discover_option_ideas(
        request.stock_candidates,
        explicit_tickers=validation.get("tickers", []),
        option_preferences=request.option_preferences,
        runtime_context={**request.runtime_context, "requested": True},
        max_underlyings=request.max_underlyings,
        max_contracts_per_ticker=request.max_contracts_per_ticker,
    )
    result["validated_tickers"] = validation.get("tickers", [])
    result["route"] = "/api/options/discover"
    return result


@app.get("/")
async def read_index():
    return FileResponse("ui/templates/index.html")


@app.get("/health")
async def health():
    return {
        "ok": True,
        "service": "trading_ai",
        "status": "running",
    }


@app.get("/api/status")
async def api_status(db_path: str = "strategy_library.db"):
    return await run_blocking_backend_call(_status_payload, db_path=db_path)


@app.get("/api/frontend-debug")
async def api_frontend_debug(db_path: str = "strategy_library.db"):
    return await run_blocking_backend_call(_frontend_debug_payload, db_path=db_path)


@app.get("/api/readiness")
async def api_readiness(db_path: str = "strategy_library.db", include_live_checks: bool = False):
    return await run_blocking_backend_call(
        check_runtime_readiness,
        {"DATABASE_PATH": db_path},
        include_live_checks=include_live_checks,
    )


@app.get("/api/db-status")
async def api_db_status(db_path: str = "strategy_library.db"):
    return await run_blocking_backend_call(_db_status_payload, db_path=db_path)


@app.get("/api/trades")
async def api_trades(db_path: str = "strategy_library.db"):
    result = await run_blocking_backend_call(get_trade_history, db_path=db_path)
    if isinstance(result, dict) and result.get("source") == "api_bridge" and result.get("ok") is False:
        return result
    if isinstance(result, dict) and result.get("ok") is False:
        return _error_response(result.get("error", "Failed to load trades."))
    trades = result if isinstance(result, list) else result.get("data", []) if isinstance(result, dict) else []
    return {"ok": True, "trades": trades if isinstance(trades, list) else [], "paper_trading_only": True}


@app.get("/api/trades/{recommendation_id}")
async def api_trade_detail(recommendation_id: int, db_path: str = "strategy_library.db"):
    def _payload() -> dict:
        recommendation = get_recommendation(recommendation_id, db_path=db_path)
        if not recommendation:
            return {"ok": False, "error": f"Trade not found: {recommendation_id}", "status_code": 404}
        reviews = get_trade_reviews(recommendation_id=recommendation_id, db_path=db_path)
        return {
            "ok": True,
            "trade": recommendation,
            "reviews": reviews,
            "paper_trading_only": True,
            "errors": [],
        }

    result = await run_blocking_backend_call(_payload)
    if result.get("status_code") == 404:
        return _error_response(result.get("error", "Trade not found."), status_code=404)
    return result


@app.get("/api/performance")
async def api_performance(db_path: str = "strategy_library.db"):
    return await run_blocking_backend_call(_performance_payload, db_path=db_path)


@app.get("/api/alerts")
async def api_alerts(db_path: str = "strategy_library.db", limit: int = 50, severity: str | None = None):
    return await run_blocking_backend_call(list_alerts, db_path=db_path, limit=limit, severity=severity)


@app.get("/api/jobs")
async def api_jobs(db_path: str = "strategy_library.db", limit: int = 30):
    def _payload() -> dict:
        registered = list_registered_jobs()
        history = list_job_runs(db_path=db_path, limit=limit)
        return {"ok": bool(registered.get("ok")) and bool(history.get("ok")), "registered_jobs": registered, "job_history": history}

    return await run_blocking_backend_call(_payload)


@app.get("/api/reports/performance")
async def api_performance_report(format: str = "dict", db_path: str = "strategy_library.db"):
    return await run_blocking_backend_call(generate_performance_diagnostics_report, db_path=db_path, format=format)


@app.get("/api/stress/scenarios")
async def api_stress_scenarios():
    return await run_blocking_backend_call(list_stress_scenarios)


@app.get("/api/stress/suite")
async def api_stress_suite():
    return await run_blocking_backend_call(run_default_stress_suite)


@app.post("/api/planning/validate")
async def api_planning_validate(request: PlanningValidateRequest):
    return await run_blocking_backend_call(
        validate_scan_plan,
        request.plan,
        runtime_context=request.runtime_context,
    )


@app.post("/api/planning/propose")
async def api_planning_propose(request: PlanningProposeRequest):
    return await run_blocking_backend_call(
        propose_scan_plan,
        request.message,
        runtime_context=request.runtime_context,
        user_preferences=request.user_preferences,
        request_id=request.request_id,
        provider=request.provider,
    )


@app.post("/api/planning/execute")
async def api_planning_execute(request: PlanningExecuteRequest):
    return await run_blocking_backend_call(
        execute_scan_plan,
        request.plan,
        runtime_context=request.runtime_context,
        db_path=request.db_path,
        timeout_seconds=_planning_execution_timeout_seconds(),
    )


@app.post("/api/planning/execute-adaptive")
async def api_planning_execute_adaptive(request: PlanningExecuteAdaptiveRequest):
    return await run_blocking_backend_call(
        execute_adaptive_scan_plan,
        request.plan,
        runtime_context=request.runtime_context,
        db_path=request.db_path,
        message=request.message,
        provider=request.provider,
        timeout_seconds=_planning_execution_timeout_seconds(),
    )


@app.post("/api/research/current")
async def api_research_current(request: CurrentResearchRequest):
    return await run_blocking_backend_call(
        build_current_research,
        request.tickers,
        scopes=request.scopes,
        request_id=request.request_id,
        as_of=request.as_of,
        provider=request.provider,
    )


@app.get("/api/learning/status")
async def api_learning_status(db_path: str = "strategy_library.db"):
    return await run_blocking_backend_call(get_learning_status, db_path=db_path)


@app.post("/api/learning/grade-outcomes")
async def api_learning_grade_outcomes(request: LearningGradeOutcomesRequest):
    return await run_blocking_backend_call(
        grade_mature_candidate_outcomes,
        db_path=request.db_path,
        as_of=request.as_of,
        horizons=request.horizons,
    )


@app.post("/api/learning/evaluate-policy")
async def api_learning_evaluate_policy(request: LearningEvaluatePolicyRequest):
    return await run_blocking_backend_call(
        evaluate_policy_walk_forward,
        request.candidate_policy,
        baseline_policy_version=request.baseline_policy_version,
        db_path=request.db_path,
        config=request.config,
    )


@app.post("/api/learning/proposals")
async def api_learning_proposals(request: LearningProposalRequest):
    return await run_blocking_backend_call(
        create_policy_proposal,
        request.proposed_policy,
        baseline_policy_version=request.baseline_policy_version,
        created_by=request.created_by,
        db_path=request.db_path,
    )


@app.post("/api/learning/promote")
async def api_learning_promote(request: LearningPromoteRequest):
    return await run_blocking_backend_call(
        promote_policy_proposal,
        proposal_id=request.proposal_id,
        approved_by=request.approved_by,
        approval_reason=request.approval_reason,
        expected_current_policy_version=request.expected_current_policy_version,
        confirm=request.confirm,
        db_path=request.db_path,
    )


@app.get("/api/learning/policies")
async def api_learning_policies(db_path: str = "strategy_library.db"):
    return await run_blocking_backend_call(list_policies, db_path=db_path, include_policy_json=True)


@app.get("/diagnostics/environment")
async def diagnostics_environment(db_path: str = "strategy_library.db"):
    return await run_blocking_backend_call(check_environment, db_path=db_path)


@app.post("/diagnostics/live-dry-run")
async def diagnostics_live_dry_run(request: LiveDryRunRequest):
    return await run_blocking_backend_call(
        run_provider_dry_run,
        ticker=request.ticker,
        include_market_data=request.include_market_data,
        include_news=request.include_news,
        include_sec_filings=request.include_sec_filings,
        include_earnings_transcripts=request.include_earnings_transcripts,
        include_options=request.include_options,
        include_memory=request.include_memory,
        db_path=request.db_path,
    )


@app.get("/predict/{ticker}")
async def predict_stock(ticker: str):
    """API endpoint to get the legacy raw prediction dossier when available."""
    if LEGACY_PREDICTION_DOSSIER is None:
        return _error_response(
            f"Legacy prediction dossier is unavailable: {LEGACY_PREDICTION_DOSSIER_ERROR or 'missing dependency or model artifact'}",
            status_code=503,
        )

    return await run_blocking_backend_call(LEGACY_PREDICTION_DOSSIER, ticker)


@app.post("/ask")
async def ask(request: AskRequest):
    """
    The main endpoint for the chat interface. It takes a natural language
    question and returns a synthesized answer from the Translator AI.
    """
    timeout_seconds = _chat_scan_timeout_seconds() if _is_trade_question(request.question) else None
    result = await run_blocking_backend_call(_chat_payload, request.question, timeout_seconds=timeout_seconds)
    if _is_backend_timeout(result):
        result = _chat_scan_timeout_payload(request.question, timeout_seconds or _chat_scan_timeout_seconds(), result)
    return {"answer": result.get("answer"), **result}


@app.post("/api/chat")
async def api_chat(request: ChatRequest):
    timeout_seconds = _chat_scan_timeout_seconds() if _is_trade_question(request.message) else None
    result = await run_blocking_backend_call(_chat_payload, request.message, db_path=request.db_path, timeout_seconds=timeout_seconds)
    if _is_backend_timeout(result):
        return _chat_scan_timeout_payload(request.message, timeout_seconds or _chat_scan_timeout_seconds(), result)
    return result


@app.post("/api/scan")
async def api_scan(request: PaperCycleRequest):
    return await paper_cycle(request)


@app.post("/api/options/strategies")
async def api_options_strategies(request: OptionsStrategiesRequest):
    return await run_blocking_backend_call(_options_strategies_payload, request)


@app.post("/api/options/discover")
async def api_options_discover(request: OptionsDiscoverRequest):
    return await run_blocking_backend_call(_options_discover_payload, request)


@app.post("/api/annotations")
async def api_annotations(request: AnnotationRequest):
    return await run_blocking_backend_call(
        add_human_annotation,
        db_path=request.db_path,
        entity_type=request.entity_type,
        annotation_type=request.annotation_type,
        rating=request.rating,
        label=request.label,
        notes=request.notes,
        entity_id=request.entity_id,
        ticker=request.ticker,
        setup_type=request.setup_type,
        payload=request.payload,
    )


@app.post("/api/system/config-check")
async def api_system_config_check(request: UpdateOutcomesRequest):
    return await run_blocking_backend_call(validate_startup_config, {"DATABASE_PATH": request.db_path})


@app.post("/api/system/readiness-check")
async def api_system_readiness_check(request: UpdateOutcomesRequest):
    return await run_blocking_backend_call(check_runtime_readiness, {"DATABASE_PATH": request.db_path}, include_live_checks=False)


@app.post("/api/system/live-dry-run")
async def api_system_live_dry_run(request: LiveDryRunRequest):
    return await diagnostics_live_dry_run(request)


@app.post("/brain/weekly-trade-hunt")
async def brain_weekly_trade_hunt(request: WeeklyTradeHuntRequest):
    result = await run_blocking_backend_call(
        run_weekly_trade_hunt,
        universe=request.universe,
        max_tickers=request.max_tickers,
        profiles=request.profiles,
        max_trades=request.max_trades,
        min_trades=request.min_trades,
        include_catalysts=request.include_catalysts,
        include_market_regime=request.include_market_regime,
        include_relative_strength=request.include_relative_strength,
        include_research_briefs=request.include_research_briefs,
        include_options=request.include_options,
        prefer_options=request.prefer_options,
        max_option_contracts_per_trade=request.max_option_contracts_per_trade,
        include_portfolio_risk=request.include_portfolio_risk,
        include_position_sizing=request.include_position_sizing,
        include_memory_context=request.include_memory_context,
        store_memory=request.store_memory,
        account_size=request.account_size,
        risk_mode=request.risk_mode,
        auto_log=request.auto_log,
        db_path=request.db_path,
    )
    if not result.get("ok"):
        return _error_response(_extract_error(result, "Weekly trade hunt failed."))
    return result


@app.get("/brain/review-ticker/{ticker}")
async def brain_review_ticker(
    ticker: str,
    include_catalysts: bool = True,
    include_research_brief: bool = True,
    include_sec_filings: bool = True,
    include_earnings_transcripts: bool = True,
    include_options: bool = False,
    include_memory_context: bool = True,
    db_path: str = "strategy_library.db",
):
    result = await run_blocking_backend_call(
        review_ticker_opportunity,
        ticker=ticker,
        include_catalysts=include_catalysts,
        include_research_brief=include_research_brief,
        include_sec_filings=include_sec_filings,
        include_earnings_transcripts=include_earnings_transcripts,
        include_options=include_options,
        include_memory_context=include_memory_context,
        db_path=db_path,
    )
    if not result.get("ok"):
        return _error_response(_extract_error(result, "Ticker review failed."))
    return result


@app.post("/brain/monitor-open-trades")
async def brain_monitor_open_trades(request: MonitorOpenTradesRequest):
    result = await run_blocking_backend_call(
        monitor_open_trades,
        update_outcomes=request.update_outcomes,
        db_path=request.db_path,
    )
    if not result.get("ok"):
        return _error_response(_extract_error(result, "Open trade monitoring failed."))
    return result


@app.get("/trades/open")
async def trades_open(db_path: str = "strategy_library.db"):
    result = await run_blocking_backend_call(get_open_recommendations, db_path=db_path)
    if isinstance(result, dict) and result.get("source") == "api_bridge" and result.get("ok") is False:
        return result
    return {
        "ok": True,
        "recommendations": result.get("data", []) if isinstance(result, dict) and "data" in result else result,
    }


@app.get("/trades/performance")
async def trades_performance(db_path: str = "strategy_library.db"):
    def _payload() -> dict:
        return {
            "ok": True,
            "win_loss_record": get_win_loss_record(db_path=db_path),
            "strategy_performance": get_strategy_performance(db_path=db_path),
        }

    return await run_blocking_backend_call(_payload)


@app.post("/trades/update-outcomes")
async def trades_update_outcomes(request: UpdateOutcomesRequest):
    return await run_blocking_backend_call(update_open_recommendations, db_path=request.db_path)


@app.post("/paper/cycle")
async def paper_cycle(request: PaperCycleRequest):
    result = await run_blocking_backend_call(_run_paper_cycle_payload, request)
    if not result.get("ok"):
        return _error_response(_extract_error(result, "Paper trading cycle failed."))
    return result


@app.post("/paper/review")
async def paper_review(request: PaperReviewRequest):
    result = await run_blocking_backend_call(
        review_paper_portfolio,
        update_outcomes=request.update_outcomes,
        include_trade_reviews=request.include_trade_reviews,
        store_review_memory=request.store_review_memory,
        db_path=request.db_path,
    )
    if not result.get("ok"):
        return _error_response(_extract_error(result, "Paper portfolio review failed."))
    return result


@app.get("/paper/summary")
async def paper_summary(db_path: str = "strategy_library.db"):
    result = await run_blocking_backend_call(get_paper_trading_summary, db_path=db_path)
    if not result.get("ok"):
        return _error_response(_extract_error(result, "Paper trading summary failed."))
    return result


@app.post("/reports/generate")
async def reports_generate(request: ReportGenerateRequest):
    result = await run_blocking_backend_call(
        generate_report_tool,
        report_type=request.report_type,
        payload=request.payload,
        format=request.format,
        db_path=request.db_path,
    )
    if not result.get("ok"):
        return _error_response(result.get("error", "Report generation failed."))
    return result


@app.get("/reports/paper-summary")
async def reports_paper_summary(
    format: str = "markdown",
    db_path: str = "strategy_library.db",
):
    result = await run_blocking_backend_call(
        generate_report_tool,
        report_type="full_paper_trading",
        payload={},
        format=format,
        db_path=db_path,
    )
    if not result.get("ok"):
        return _error_response(result.get("error", "Paper summary report generation failed."))
    return result


@app.post("/journal/review-closed-trades")
async def journal_review_closed_trades(request: JournalReviewClosedTradesRequest):
    result = await run_blocking_backend_call(
        review_closed_trades,
        db_path=request.db_path,
        store_memory=request.store_memory,
    )
    if not result.get("ok"):
        return _error_response(_extract_error(result, "Closed trade review failed."))
    return result


@app.get("/journal/reviews")
async def journal_reviews(
    recommendation_id: int | None = None,
    ticker: str | None = None,
    db_path: str = "strategy_library.db",
):
    result = await run_blocking_backend_call(
        get_trade_reviews,
        recommendation_id=recommendation_id,
        ticker=ticker,
        db_path=db_path,
    )
    if not result.get("ok"):
        return _error_response(result.get("error", "Failed to load trade reviews."))
    return result
