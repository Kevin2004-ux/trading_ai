from translator.output_validator import validate_gemini_output
from translator.response_formatter import (
    format_deterministic_fallback_response,
    format_validated_trade_response,
)
from translator.output_schemas import weekly_trade_hunt_response


def _sample_result() -> dict:
    return {
        "summary": {"selected_count": 1, "logged_count": 0, "message": "Deterministic sample result."},
        "decision_result": {
            "final_recommendations": [
                {
                    "ticker": "AAPL",
                    "entry_price": 100.0,
                    "target_price": 112.0,
                    "stop_loss": 94.0,
                    "risk_reward": 2.0,
                    "thesis": "passed deterministic constraints",
                }
            ],
            "not_selected": [{"ticker": "TSLA", "reason": "failed deterministic rules"}],
        },
        "selection_result": {"watchlist_alternatives": [{"ticker": "MSFT", "rejection_reason": "watchlist only"}]},
        "scan_result": {"data_quality_summary": {"warnings": ["Historical fallback enabled."]}},
    }


def _valid_output() -> dict:
    return weekly_trade_hunt_response(
        final_paper_trades=[
            {
                "ticker": "AAPL",
                "entry_price": 100.0,
                "target_price": 112.0,
                "stop_loss": 94.0,
                "risk_reward": 2.0,
                "paper_logged": False,
            }
        ],
        watchlist=[{"ticker": "MSFT", "reason": "watchlist only"}],
        data_quality_warnings=["Historical fallback enabled."],
        plain_english_summary="One paper-trading-only setup qualified. No trade was logged.",
    )


def test_format_validated_trade_response_uses_safe_valid_output():
    validation = validate_gemini_output(_valid_output(), _sample_result())
    text = format_validated_trade_response(validation, fallback_result=_sample_result())

    assert "Paper trading only" in text
    assert "AAPL" in text
    assert "$100.00" in text
    assert "MSFT" in text


def test_format_validated_trade_response_falls_back_when_validation_blocks():
    output = _valid_output()
    output["final_paper_trades"][0]["ticker"] = "META"
    validation = validate_gemini_output(output, _sample_result())

    text = format_validated_trade_response(validation, fallback_result=_sample_result())

    assert "META" not in text
    assert "AAPL" in text
    assert "Deterministic sample result" in text


def test_format_deterministic_fallback_response_includes_warnings_and_rejections():
    text = format_deterministic_fallback_response(_sample_result())

    assert "Paper trading only" in text
    assert "Selected count: 1" in text
    assert "TSLA" in text
    assert "Historical fallback enabled" in text
