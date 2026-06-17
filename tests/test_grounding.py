from translator.grounding import check_claim_against_grounding, extract_grounding_facts


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
            ],
            "not_selected": [{"ticker": "TSLA", "reason": "rejected"}],
        },
        "selection_result": {
            "watchlist_alternatives": [{"ticker": "MSFT"}],
            "rejected_candidates": [{"ticker": "NVDA"}],
        },
        "scan_result": {"data_quality_summary": {"warnings": ["Historical fallback enabled."]}},
    }


def test_extract_grounding_facts_collects_candidate_buckets():
    facts = extract_grounding_facts(_sample_result())

    assert facts["selected_tickers"] == ["AAPL"]
    assert "MSFT" in facts["watchlist_tickers"]
    assert "TSLA" in facts["rejected_tickers"]
    assert "NVDA" in facts["rejected_tickers"]
    assert facts["trade_facts"]["AAPL"]["entry_price"] == 100.0
    assert facts["data_quality_warnings"] == ["Historical fallback enabled."]


def test_check_claim_against_grounding_accepts_faithful_claim():
    facts = extract_grounding_facts(_sample_result())

    result = check_claim_against_grounding({"ticker": "AAPL", "entry_price": 100.0, "target_price": 112.0}, facts)

    assert result["ok"] is True


def test_check_claim_against_grounding_rejects_mismatched_price():
    facts = extract_grounding_facts(_sample_result())

    result = check_claim_against_grounding({"ticker": "AAPL", "entry_price": 105.0}, facts)

    assert result["ok"] is False
    assert result["code"] == "mismatched_entry_price"


def test_check_claim_against_grounding_rejects_fabricated_ticker():
    facts = extract_grounding_facts(_sample_result())

    result = check_claim_against_grounding({"ticker": "META", "entry_price": 100.0}, facts)

    assert result["ok"] is False
    assert result["code"] == "fabricated_ticker"
