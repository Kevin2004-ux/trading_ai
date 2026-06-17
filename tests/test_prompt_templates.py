from translator.prompt_templates import (
    build_gemini_system_prompt,
    build_no_trade_prompt,
    build_weekly_trade_hunt_prompt,
)


def _sample_result() -> dict:
    return {
        "summary": {"selected_count": 1, "logged_count": 0},
        "decision_result": {
            "final_recommendations": [
                {
                    "ticker": "AAPL",
                    "entry_price": 100.0,
                    "target_price": 112.0,
                    "stop_loss": 94.0,
                    "risk_reward": 2.0,
                }
            ]
        },
        "selection_result": {
            "watchlist_alternatives": [{"ticker": "MSFT"}],
            "rejected_candidates": [{"ticker": "TSLA", "rejection_reason": "failed risk/reward"}],
        },
    }


def test_system_prompt_contains_core_safety_rules():
    prompt = build_gemini_system_prompt()

    assert "Do not invent tickers" in prompt
    assert "Paper trading/simulation only" in prompt
    assert "not a financial advisor" in prompt
    assert "Never imply real brokerage execution" in prompt
    assert "Return valid JSON" in prompt


def test_weekly_trade_hunt_prompt_includes_deterministic_result():
    prompt = build_weekly_trade_hunt_prompt("find trades", _sample_result())

    assert 'response_type="weekly_trade_hunt"' in prompt
    assert "AAPL" in prompt
    assert '"selected_count": 1' in prompt
    assert "Do not create any final_paper_trades" in prompt


def test_no_trade_prompt_preserves_no_trade_instruction():
    prompt = build_no_trade_prompt({"summary": {"selected_count": 0}, "selection_result": {"rejected_candidates": [{"ticker": "AAPL"}]}})

    assert 'response_type="no_trade"' in prompt
    assert "no final paper trade qualified" in prompt.lower()
    assert "Preserve all risk and data-quality warnings" in prompt
