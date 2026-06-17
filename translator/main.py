# translator/main.py
from __future__ import annotations

import os
from typing import Callable

from dotenv import load_dotenv

from tools.agent_tools import (
    build_trade_review_tool,
    evaluate_option_mispricing_tool,
    generate_report_tool,
    get_trade_reviews_tool,
    get_candidate_details_tool,
    get_catalyst_brain_tool,
    get_deep_research_brief_tool,
    get_earnings_transcript_brain_tool,
    get_market_regime_tool,
    get_open_recommendations_tool,
    calculate_position_size_tool,
    find_similar_setups_tool,
    get_portfolio_risk_tool,
    get_relative_strength_tool,
    get_sec_filing_brain_tool,
    get_statistical_brain_tool,
    get_strategy_performance_tool,
    get_win_loss_record_tool,
    log_recommendation_tool,
    review_closed_trades_tool,
    run_paper_trading_tool,
    run_trading_brain_tool,
    scan_candidates_tool,
    scan_options_for_candidate_tool,
    scan_market_for_weekly_trades_tool,
    search_trade_memory_tool,
    store_trade_memory_tool,
    update_outcomes_tool,
)

from .prompts import SYSTEM_PROMPT
from .prompt_templates import build_gemini_system_prompt
from .output_validator import validate_gemini_output
from .response_formatter import format_validated_trade_response

try:
    import google.generativeai as genai
except ImportError:  # pragma: no cover - exercised indirectly in tests
    genai = None


load_dotenv(override=True)

MODEL_NAME = "gemini-1.5-pro"
_MODEL = None
_MODEL_INIT_ERROR: str | None = None


def _load_optional_prediction_dossier() -> Callable | None:
    try:
        from tools.get_prediction_dossier import get_prediction_dossier

        return get_prediction_dossier
    except Exception:
        return None


LEGACY_PREDICTION_DOSSIER_TOOL = _load_optional_prediction_dossier()

REGISTERED_TOOLS = [
    run_paper_trading_tool,
    run_trading_brain_tool,
    scan_market_for_weekly_trades_tool,
    scan_candidates_tool,
    scan_options_for_candidate_tool,
    evaluate_option_mispricing_tool,
    get_market_regime_tool,
    calculate_position_size_tool,
    search_trade_memory_tool,
    store_trade_memory_tool,
    find_similar_setups_tool,
    build_trade_review_tool,
    review_closed_trades_tool,
    get_trade_reviews_tool,
    generate_report_tool,
    get_relative_strength_tool,
    get_portfolio_risk_tool,
    get_deep_research_brief_tool,
    get_sec_filing_brain_tool,
    get_earnings_transcript_brain_tool,
    get_candidate_details_tool,
    log_recommendation_tool,
    get_open_recommendations_tool,
    update_outcomes_tool,
    get_win_loss_record_tool,
    get_strategy_performance_tool,
    get_statistical_brain_tool,
    get_catalyst_brain_tool,
]
if LEGACY_PREDICTION_DOSSIER_TOOL is not None:
    REGISTERED_TOOLS.append(LEGACY_PREDICTION_DOSSIER_TOOL)

REGISTERED_TOOL_NAMES = [tool.__name__ for tool in REGISTERED_TOOLS]


def get_registered_tools() -> list[Callable]:
    return list(REGISTERED_TOOLS)


def _build_model():
    global _MODEL
    global _MODEL_INIT_ERROR

    if _MODEL is not None:
        return _MODEL

    if genai is None:
        _MODEL_INIT_ERROR = "google.generativeai is not installed."
        return None

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        _MODEL_INIT_ERROR = "GEMINI_API_KEY is not configured."
        return None

    try:
        genai.configure(api_key=api_key)
        _MODEL = genai.GenerativeModel(
            model_name=MODEL_NAME,
            tools=get_registered_tools(),
            system_instruction=build_gemini_system_prompt(),
        )
        _MODEL_INIT_ERROR = None
        return _MODEL
    except Exception as exc:  # pragma: no cover - depends on SDK/runtime
        _MODEL_INIT_ERROR = str(exc)
        return None


def get_model_init_error() -> str | None:
    _build_model()
    return _MODEL_INIT_ERROR


def ask_translator(question: str) -> str:
    """
    Sends a user's question to the Gemini model and returns its response.
    """
    model = _build_model()
    if model is None:
        return "Sorry, the AI translator is unavailable right now because the Gemini runtime is not fully configured."

    try:
        chat = model.start_chat(enable_automatic_function_calling=True)
        response = chat.send_message(question)
        return response.text
    except Exception as exc:
        print(f"An error occurred with the generative model: {exc}")
        return "Sorry, an error occurred while contacting the AI."


def validate_and_format_gemini_trade_output(gemini_output: dict | str, trading_brain_result: dict) -> dict:
    validation = validate_gemini_output(gemini_output, trading_brain_result)
    return {
        "ok": bool(validation.get("ok")),
        "validation": validation,
        "formatted_response": format_validated_trade_response(validation, fallback_result=trading_brain_result),
        "deterministic_fallback_used": not bool(validation.get("safe_to_show_user")),
    }
