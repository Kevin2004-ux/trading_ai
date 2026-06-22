# ui/app.py

from __future__ import annotations

from typing import Callable
import os
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
from ideas import build_best_available_ideas, format_best_ideas_response  # noqa: E402
from memory.annotation_store import add_human_annotation  # noqa: E402
from options.strategy_builder import build_option_strategy_candidates  # noqa: E402
from paper.paper_trader import (  # noqa: E402
    get_paper_trading_summary,
    review_paper_portfolio,
    run_paper_trade_cycle,
)
from realtime.market_data import get_market_snapshot  # noqa: E402
from realtime.options_chain import get_options_chain  # noqa: E402
from reports.report_generator import generate_performance_diagnostics_report  # noqa: E402
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


def _error_response(message: str, status_code: int = 500) -> JSONResponse:
    return JSONResponse(status_code=status_code, content={"ok": False, "error": message})


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
    return any(term in normalized_compact for term in terms)


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


def _enrich_with_best_ideas(result: dict, include_options: bool = True) -> dict:
    if not isinstance(result, dict):
        return result
    enriched = dict(result)
    best_ideas = build_best_available_ideas(enriched, config={"include_options": include_options})
    enriched["best_available_ideas"] = best_ideas
    enriched["formatted_best_ideas_summary"] = format_best_ideas_response(best_ideas)
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
    return _enrich_with_best_ideas(result, include_options=request.include_options)


def _run_best_ideas_chat_scan(message: str, db_path: str) -> dict:
    wants_options = _wants_options_request(message)
    request = PaperCycleRequest(
        universe="mega_cap",
        max_tickers=25,
        max_trades=2,
        min_trades=0,
        include_options=wants_options,
        prefer_options=False,
        include_market_regime=True,
        include_relative_strength=True,
        include_portfolio_risk=True,
        include_position_sizing=True,
        db_path=db_path,
    )
    scan_result = _run_paper_cycle_payload(request)
    best_ideas = scan_result.get("best_available_ideas") if isinstance(scan_result, dict) else None
    if not isinstance(best_ideas, dict):
        best_ideas = build_best_available_ideas(scan_result if isinstance(scan_result, dict) else {})
    return {
        "scan_result": scan_result,
        "best_available_ideas": best_ideas,
        "formatted_best_ideas_summary": format_best_ideas_response(best_ideas),
        "include_options": wants_options,
    }


def _chat_payload(message: str, db_path: str = "strategy_library.db") -> dict:
    init_error = get_model_init_error()
    if _is_trade_question(message):
        best_ideas_payload = _run_best_ideas_chat_scan(message, db_path=db_path)
        best_ideas = best_ideas_payload["best_available_ideas"]
        answer = best_ideas_payload["formatted_best_ideas_summary"]
        mode = "deterministic_fallback" if init_error else "deterministic_scan"
        warnings = list(best_ideas.get("warnings", []))
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
            "scan_result": best_ideas_payload["scan_result"],
            "formatted_best_ideas_summary": answer,
            "validation": {
                "validation_status": mode,
                "safe_to_show_user": True,
                "deterministic_engine_source_of_truth": True,
                "deterministic_fallback_used": init_error is not None,
            },
            "raw_result": {
                "message": message,
                "gemini_status": "available" if init_error is None else "unavailable",
                "include_options": best_ideas_payload["include_options"],
            },
            "warnings": warnings,
            "errors": [],
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
    return {
        "ok": True,
        "backend": "running",
        "service": "trading_ai",
        "paper_trading_only": True,
        "brokerage_execution_enabled": False,
        "gemini_available": gemini_error is None,
        "gemini_status": "available" if gemini_error is None else "unavailable",
        "ibkr_configured": bool(os.getenv("IBKR_HOST") and os.getenv("IBKR_PORT")),
        "database_ready": bool(validation.get("ok")),
        "frontend_bridge": "ready",
        "readiness": readiness,
        "paper_summary": paper,
        "performance": performance,
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
    result = await run_blocking_backend_call(_chat_payload, request.question)
    return {"answer": result.get("answer"), **result}


@app.post("/api/chat")
async def api_chat(request: ChatRequest):
    return await run_blocking_backend_call(_chat_payload, request.message, db_path=request.db_path)


@app.post("/api/scan")
async def api_scan(request: PaperCycleRequest):
    return await paper_cycle(request)


@app.post("/api/options/strategies")
async def api_options_strategies(request: OptionsStrategiesRequest):
    return await run_blocking_backend_call(_options_strategies_payload, request)


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
