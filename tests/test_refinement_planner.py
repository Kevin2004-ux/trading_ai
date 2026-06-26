import pytest
from pydantic import ValidationError

import planning.refinement_controller as refinement
from planning.refinement_models import RefinementProposalModel


def _plan(**overrides):
    payload = {
        "requested_instrument": "stocks",
        "objective": "best_ideas",
        "time_horizon": "swing",
        "universes": ["large_cap"],
        "custom_tickers": [],
        "profiles": ["momentum_breakout"],
        "max_tickers": 25,
        "max_candidates": 10,
        "include_options": False,
        "prefer_options": False,
        "refinement": {"max_passes": 2},
    }
    payload.update(overrides)
    return payload


def _evaluation(**overrides):
    payload = {
        "evaluation_version": "scan_pass_evaluation_v1",
        "provider_status": "available",
        "ranking_status": "available",
        "paper_eligible_count": 0,
        "stock_watchlist_count": 1,
        "blocked_research_count": 0,
        "exact_option_count": 0,
        "option_underlying_watchlist_count": 0,
        "legitimate_ranked_count": 1,
        "top_stock_opportunity_score": 62,
        "top_option_opportunity_score": None,
        "median_stock_opportunity_score": 62,
        "failed_constraint_counts": {},
        "data_failure_count": 0,
        "partial_results": False,
        "sufficient_results": False,
        "refinement_allowed": True,
        "recommended_action": "broaden_universe",
        "reasons": ["Legitimate rankings are sparse or weak; one bounded refinement may help."],
        "warnings": [],
    }
    payload.update(overrides)
    return payload


def test_refinement_proposal_model_rejects_extra_fields():
    with pytest.raises(ValidationError):
        RefinementProposalModel.model_validate(
            {
                "action": "refine",
                "reasoning_summary": "Try a bounded universe change.",
                "adjustments": {"universes": ["growth"]},
                "hidden_chain_of_thought": "not allowed",
            }
        )


def test_deterministic_refinement_never_calls_openai(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("deterministic refinement must not call OpenAI")

    monkeypatch.setattr(refinement, "_propose_with_openai", forbidden)

    result = refinement.propose_scan_refinement(
        _plan(),
        _plan(),
        _evaluation(),
        prior_pass_summaries=[],
        provider="deterministic",
    )

    assert result["ok"] is True
    assert result["provider"] == "deterministic"
    assert result["proposal"]["action"] == "refine"
    assert result["proposal"]["adjustments"]["universes"]


def test_auto_refinement_falls_back_when_openai_unavailable(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(refinement, "_openai_sdk_available", lambda: True)

    result = refinement.propose_scan_refinement(
        _plan(),
        _plan(),
        _evaluation(),
        prior_pass_summaries=[],
        provider="auto",
    )

    assert result["provider"] == "deterministic"
    assert result["fallback_used"] is True
    assert result["proposal"]["action"] == "refine"
    assert any("api key" in warning.lower() for warning in result["warnings"])


def test_openai_refinement_uses_structured_parse(monkeypatch):
    captured = {}

    class FakeResponses:
        def parse(self, **kwargs):
            captured.update(kwargs)
            parsed = RefinementProposalModel(
                action="refine",
                reasoning_summary="Try the approved growth universe.",
                adjustments={"universes": ["growth"], "max_tickers": 50},
            )
            return type("FakeResponse", (), {"output_parsed": parsed, "usage": {"input_tokens": 10}})()

    class FakeClient:
        responses = FakeResponses()

    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setattr(refinement, "_openai_sdk_available", lambda: True)
    monkeypatch.setattr(refinement, "_create_openai_client", lambda api_key, timeout=20.0: FakeClient())

    result = refinement.propose_scan_refinement(
        _plan(),
        _plan(),
        _evaluation(),
        prior_pass_summaries=[],
        provider="openai",
    )

    assert result["provider"] == "openai"
    assert result["fallback_used"] is False
    assert captured["text_format"] is RefinementProposalModel
    assert result["proposal"]["adjustments"]["universes"] == ["growth"]
    assert result["usage"]["input_tokens"] == 10


def test_refinement_stops_when_policy_evaluation_disallows_it():
    result = refinement.propose_scan_refinement(
        _plan(),
        _plan(),
        _evaluation(refinement_allowed=False, provider_status="unavailable", ranking_status="unavailable"),
        prior_pass_summaries=[],
        provider="deterministic",
    )

    assert result["proposal"]["action"] == "stop"
    assert "stop conditions" in result["proposal"]["reasoning_summary"].lower()
