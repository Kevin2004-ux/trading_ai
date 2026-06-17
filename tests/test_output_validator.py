from translator.output_schemas import weekly_trade_hunt_response
from translator.output_validator import validate_gemini_output


def _sample_result(include_options: bool = False) -> dict:
    result = {
        "summary": {
            "selected_count": 1,
            "logged_count": 0,
            "message": "Built one final paper recommendation.",
        },
        "market_regime": {"regime": "risk_on"},
        "decision_result": {
            "final_recommendations": [
                {
                    "ticker": "AAPL",
                    "asset_type": "stock",
                    "direction": "long",
                    "entry_price": 100.0,
                    "target_price": 112.0,
                    "stop_loss": 94.0,
                    "risk_reward": 2.0,
                    "preferred_instrument": "stock",
                }
            ],
            "logged_recommendations": [],
        },
        "selection_result": {
            "watchlist_alternatives": [{"ticker": "MSFT", "rejection_reason": "watchlist only"}],
            "rejected_candidates": [{"ticker": "TSLA", "rejection_reason": "failed risk/reward"}],
        },
        "scan_result": {"data_quality_summary": {"warnings": ["Historical fallback enabled for AAPL."]}},
    }
    if include_options:
        result["option_risk_summary"] = {"blocked_count": 1}
    return result


def _valid_output() -> dict:
    return weekly_trade_hunt_response(
        market_context={"regime": "risk_on"},
        final_paper_trades=[
            {
                "ticker": "AAPL",
                "asset_type": "stock",
                "direction": "long",
                "entry_price": 100.0,
                "target_price": 112.0,
                "stop_loss": 94.0,
                "risk_reward": 2.0,
                "paper_logged": False,
                "preferred_instrument": "stock",
            }
        ],
        watchlist=[{"ticker": "MSFT", "reason": "watchlist only"}],
        rejected_summary=[{"ticker": "TSLA", "reason": "failed risk/reward"}],
        options_status={"status": "stock_only"},
        data_quality_warnings=["Historical fallback enabled for AAPL."],
        plain_english_summary="One paper-trading-only stock setup qualified. No trade was logged.",
    )


def test_validate_gemini_output_accepts_faithful_output():
    validation = validate_gemini_output(_valid_output(), _sample_result())

    assert validation["ok"] is True
    assert validation["validation_status"] == "pass"
    assert validation["safe_to_show_user"] is True


def test_validate_gemini_output_rejects_fabricated_final_trade():
    output = _valid_output()
    output["final_paper_trades"][0]["ticker"] = "META"

    validation = validate_gemini_output(output, _sample_result())

    assert validation["ok"] is False
    assert any(issue["code"] == "fabricated_final_trade" for issue in validation["issues"])


def test_validate_gemini_output_rejects_fabricated_logged_status():
    output = _valid_output()
    output["final_paper_trades"][0]["paper_logged"] = True
    output["plain_english_summary"] = "AAPL was logged and tracked for paper trading."

    validation = validate_gemini_output(output, _sample_result())

    assert validation["ok"] is False
    assert any(issue["code"] == "fabricated_logged_trade" for issue in validation["issues"])


def test_validate_gemini_output_rejects_mismatched_prices():
    output = _valid_output()
    output["final_paper_trades"][0]["entry_price"] = 101.0

    validation = validate_gemini_output(output, _sample_result())

    assert validation["ok"] is False
    assert any(issue["code"] == "mismatched_entry_price" for issue in validation["issues"])


def test_validate_gemini_output_rejects_unsupported_option_recommendation():
    output = _valid_output()
    output["final_paper_trades"][0]["preferred_instrument"] = "option"
    output["final_paper_trades"][0]["option_status"] = "research_only"
    output["options_status"] = {"status": "research_only"}

    validation = validate_gemini_output(output, _sample_result(include_options=True))

    assert validation["ok"] is False
    assert any(issue["code"] == "unsupported_option_recommendation" for issue in validation["issues"])


def test_validate_gemini_output_flags_missing_data_quality_warning():
    output = _valid_output()
    output["data_quality_warnings"] = []

    validation = validate_gemini_output(output, _sample_result())

    assert validation["validation_status"] == "warn"
    assert any(issue["code"] == "missing_data_quality_warning" for issue in validation["issues"])


def test_validate_gemini_output_rejects_certainty_and_order_language():
    output = _valid_output()
    output["plain_english_summary"] = "This paper trade is guaranteed and you should buy now."

    validation = validate_gemini_output(output, _sample_result())

    assert validation["ok"] is False
    assert any(issue["code"] == "certainty_language" for issue in validation["issues"])
    assert any(issue["code"] == "real_order_language" for issue in validation["issues"])


def test_validate_gemini_output_parses_json_string():
    import json

    validation = validate_gemini_output(json.dumps(_valid_output()), _sample_result())

    assert validation["ok"] is True
