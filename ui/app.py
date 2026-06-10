# ui/app.py

from __future__ import annotations

from typing import Callable
import sys

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

sys.path.append(".")

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
from paper.paper_trader import (  # noqa: E402
    get_paper_trading_summary,
    review_paper_portfolio,
    run_paper_trade_cycle,
)
from tools.agent_tools import generate_report_tool  # noqa: E402
from tracking.outcome_grader import update_open_recommendations  # noqa: E402
from tracking.trade_logger import (  # noqa: E402
    get_open_recommendations,
    get_strategy_performance,
    get_win_loss_record,
)
from translator.main import ask_translator  # noqa: E402


def _load_optional_prediction_dossier() -> tuple[Callable | None, str | None]:
    try:
        from tools.get_prediction_dossier import get_prediction_dossier

        return get_prediction_dossier, None
    except Exception as exc:
        return None, str(exc)


LEGACY_PREDICTION_DOSSIER, LEGACY_PREDICTION_DOSSIER_ERROR = _load_optional_prediction_dossier()

app = FastAPI(title="Trading AI API")


class AskRequest(BaseModel):
    question: str


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


@app.get("/diagnostics/environment")
async def diagnostics_environment(db_path: str = "strategy_library.db"):
    try:
        result = check_environment(db_path=db_path)
        if not result.get("ok"):
            return JSONResponse(status_code=200, content=result)
        return result
    except Exception as exc:
        return _error_response(f"Environment diagnostics failed: {exc}")


@app.post("/diagnostics/live-dry-run")
async def diagnostics_live_dry_run(request: LiveDryRunRequest):
    try:
        result = run_provider_dry_run(
            ticker=request.ticker,
            include_market_data=request.include_market_data,
            include_news=request.include_news,
            include_sec_filings=request.include_sec_filings,
            include_earnings_transcripts=request.include_earnings_transcripts,
            include_options=request.include_options,
            include_memory=request.include_memory,
            db_path=request.db_path,
        )
        if not result.get("ok") and result.get("errors"):
            return JSONResponse(status_code=200, content=result)
        return result
    except Exception as exc:
        return _error_response(f"Live dry run failed: {exc}")


@app.get("/predict/{ticker}")
async def predict_stock(ticker: str):
    """API endpoint to get the legacy raw prediction dossier when available."""
    if LEGACY_PREDICTION_DOSSIER is None:
        return _error_response(
            f"Legacy prediction dossier is unavailable: {LEGACY_PREDICTION_DOSSIER_ERROR or 'missing dependency or model artifact'}",
            status_code=503,
        )

    try:
        return LEGACY_PREDICTION_DOSSIER(ticker)
    except Exception as exc:
        return _error_response(f"Failed to build prediction dossier: {exc}")


@app.post("/ask")
async def ask(request: AskRequest):
    """
    The main endpoint for the chat interface. It takes a natural language
    question and returns a synthesized answer from the Translator AI.
    """
    try:
        answer = ask_translator(request.question)
        return {"answer": answer}
    except Exception as exc:
        return _error_response(f"Failed to process question: {exc}")


@app.post("/brain/weekly-trade-hunt")
async def brain_weekly_trade_hunt(request: WeeklyTradeHuntRequest):
    try:
        result = run_weekly_trade_hunt(
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
    except Exception as exc:
        return _error_response(f"Weekly trade hunt failed: {exc}")


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
    try:
        result = review_ticker_opportunity(
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
    except Exception as exc:
        return _error_response(f"Ticker review failed: {exc}")


@app.post("/brain/monitor-open-trades")
async def brain_monitor_open_trades(request: MonitorOpenTradesRequest):
    try:
        result = monitor_open_trades(
            update_outcomes=request.update_outcomes,
            db_path=request.db_path,
        )
        if not result.get("ok"):
            return _error_response(_extract_error(result, "Open trade monitoring failed."))
        return result
    except Exception as exc:
        return _error_response(f"Open trade monitoring failed: {exc}")


@app.get("/trades/open")
async def trades_open(db_path: str = "strategy_library.db"):
    try:
        result = get_open_recommendations(db_path=db_path)
        if isinstance(result, dict) and result.get("ok") is False:
            return _error_response(result.get("error", "Failed to load open trades."))
        return {
            "ok": True,
            "recommendations": result,
        }
    except Exception as exc:
        return _error_response(f"Failed to load open trades: {exc}")


@app.get("/trades/performance")
async def trades_performance(db_path: str = "strategy_library.db"):
    try:
        win_loss_record = get_win_loss_record(db_path=db_path)
        if isinstance(win_loss_record, dict) and win_loss_record.get("ok") is False:
            return _error_response(win_loss_record.get("error", "Failed to load win/loss record."))

        strategy_performance = get_strategy_performance(db_path=db_path)
        if isinstance(strategy_performance, dict) and strategy_performance.get("ok") is False:
            return _error_response(strategy_performance.get("error", "Failed to load strategy performance."))

        return {
            "ok": True,
            "win_loss_record": win_loss_record,
            "strategy_performance": strategy_performance,
        }
    except Exception as exc:
        return _error_response(f"Failed to load trade performance: {exc}")


@app.post("/trades/update-outcomes")
async def trades_update_outcomes(request: UpdateOutcomesRequest):
    try:
        result = update_open_recommendations(db_path=request.db_path)
        if not result.get("ok"):
            return _error_response(_extract_error(result, "Failed to update trade outcomes."))
        return result
    except Exception as exc:
        return _error_response(f"Failed to update trade outcomes: {exc}")


@app.post("/paper/cycle")
async def paper_cycle(request: PaperCycleRequest):
    try:
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
        if not result.get("ok"):
            return _error_response(_extract_error(result, "Paper trading cycle failed."))
        return result
    except Exception as exc:
        return _error_response(f"Paper trading cycle failed: {exc}")


@app.post("/paper/review")
async def paper_review(request: PaperReviewRequest):
    try:
        result = review_paper_portfolio(
            update_outcomes=request.update_outcomes,
            include_trade_reviews=request.include_trade_reviews,
            store_review_memory=request.store_review_memory,
            db_path=request.db_path,
        )
        if not result.get("ok"):
            return _error_response(_extract_error(result, "Paper portfolio review failed."))
        return result
    except Exception as exc:
        return _error_response(f"Paper portfolio review failed: {exc}")


@app.get("/paper/summary")
async def paper_summary(db_path: str = "strategy_library.db"):
    try:
        result = get_paper_trading_summary(db_path=db_path)
        if not result.get("ok"):
            return _error_response(_extract_error(result, "Paper trading summary failed."))
        return result
    except Exception as exc:
        return _error_response(f"Paper trading summary failed: {exc}")


@app.post("/reports/generate")
async def reports_generate(request: ReportGenerateRequest):
    try:
        result = generate_report_tool(
            report_type=request.report_type,
            payload=request.payload,
            format=request.format,
            db_path=request.db_path,
        )
        if not result.get("ok"):
            return _error_response(result.get("error", "Report generation failed."))
        return result
    except Exception as exc:
        return _error_response(f"Report generation failed: {exc}")


@app.get("/reports/paper-summary")
async def reports_paper_summary(
    format: str = "markdown",
    db_path: str = "strategy_library.db",
):
    try:
        result = generate_report_tool(
            report_type="full_paper_trading",
            payload={},
            format=format,
            db_path=db_path,
        )
        if not result.get("ok"):
            return _error_response(result.get("error", "Paper summary report generation failed."))
        return result
    except Exception as exc:
        return _error_response(f"Paper summary report generation failed: {exc}")


@app.post("/journal/review-closed-trades")
async def journal_review_closed_trades(request: JournalReviewClosedTradesRequest):
    try:
        result = review_closed_trades(
            db_path=request.db_path,
            store_memory=request.store_memory,
        )
        if not result.get("ok"):
            return _error_response(_extract_error(result, "Closed trade review failed."))
        return result
    except Exception as exc:
        return _error_response(f"Closed trade review failed: {exc}")


@app.get("/journal/reviews")
async def journal_reviews(
    recommendation_id: int | None = None,
    ticker: str | None = None,
    db_path: str = "strategy_library.db",
):
    try:
        result = get_trade_reviews(
            recommendation_id=recommendation_id,
            ticker=ticker,
            db_path=db_path,
        )
        if not result.get("ok"):
            return _error_response(result.get("error", "Failed to load trade reviews."))
        return result
    except Exception as exc:
        return _error_response(f"Failed to load trade reviews: {exc}")
