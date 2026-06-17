from datetime import datetime, timezone

from memory.memory_context import build_memory_decision_context, build_memory_query_context


def _candidate(**overrides):
    payload = {
        "ticker": "AAPL",
        "setup_type": "relative_strength",
        "direction": "long",
        "asset_type": "stock",
        "recommendation_status": "recommendable",
    }
    payload.update(overrides)
    return payload


def _retrieval(outcome="win", score=0.9):
    return {
        "ok": True,
        "matches": [
            {
                "memory_id": "m1",
                "score": score,
                "metadata": {
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "outcome": outcome,
                    "outcome_verified": True,
                },
            }
        ],
        "error": None,
    }


def test_build_memory_query_context_returns_structured_query():
    result = build_memory_query_context(_candidate(), market_context={"regime": "risk_on"})

    assert result["ok"] is True
    assert result["ticker"] == "AAPL"
    assert result["setup_type"] == "relative_strength"
    assert "AAPL" in result["query_text"]
    assert result["structured_context"]["market_context"]["regime"] == "risk_on"


def test_positive_verified_memory_adds_small_support():
    result = build_memory_decision_context(_candidate(), retrieval_result=_retrieval(outcome="win"))

    assert result["ok"] is True
    assert result["retrieval_quality"]["usable_for_decision_support"] is True
    assert result["memory_impact"]["trade_impact"] == "supportive"
    assert result["memory_impact"]["score_adjustment"] > 0


def test_negative_verified_memory_reduces_score_and_risk():
    result = build_memory_decision_context(_candidate(), retrieval_result=_retrieval(outcome="loss"))

    assert result["memory_impact"]["trade_impact"] == "caution"
    assert result["memory_impact"]["score_adjustment"] < 0
    assert result["memory_impact"]["risk_multiplier"] < 1.0


def test_memory_context_cannot_unblock_hard_rejected_candidate():
    result = build_memory_decision_context(_candidate(recommendation_status="rejected"), retrieval_result=_retrieval(outcome="win"))

    assert result["memory_impact"]["trade_impact"] == "ignored"
    assert result["memory_impact"]["score_adjustment"] <= 0


def test_medium_similarity_is_explanation_only_and_does_not_adjust():
    result = build_memory_decision_context(_candidate(), retrieval_result=_retrieval(score=0.78))

    assert result["retrieval_quality"]["usable_for_explanation"] is True
    assert result["retrieval_quality"]["usable_for_decision_support"] is False
    assert result["memory_impact"]["score_adjustment"] == 0.0
