import os

import pytest

import planning.ai_planner as ai_planner
from planning import PlannerProposalModel, ScanPlan, propose_scan_plan


def test_deterministic_provider_never_calls_openai(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

    def forbidden(*args, **kwargs):
        raise AssertionError("deterministic planner must not call OpenAI")

    monkeypatch.setattr(ai_planner, "_propose_with_openai", forbidden)

    result = propose_scan_plan("Give me your best stock ideas. No options.", provider="deterministic", request_id="req-1")

    assert result["ok"] is True
    assert result["provider"] == "deterministic"
    assert result["status"] == "deterministic_planned"
    assert result["fallback_used"] is False
    assert result["approved_plan"]["requested_instrument"] == "stocks"
    assert result["approved_plan"]["include_options"] is False
    assert result["approved_plan"]["prefer_options"] is False


def test_auto_provider_falls_back_without_openai_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(ai_planner, "_openai_sdk_available", lambda: True)

    result = propose_scan_plan("Find the best trades this week", provider="auto", request_id="req-2")

    assert result["ok"] is True
    assert result["provider"] == "auto"
    assert result["status"] == "deterministic_planned"
    assert result["fallback_used"] is True
    assert result["ai_available"] is False
    assert "api key" in " ".join(result["warnings"]).lower()


def test_openai_success_uses_responses_parse_structured_output(monkeypatch):
    captured = {}

    class FakeResponses:
        def parse(self, **kwargs):
            captured.update(kwargs)
            parsed = PlannerProposalModel(
                intent={"objective": "best_ideas", "requested_instrument": "stocks"},
                proposed_plan=ScanPlan(
                    requested_instrument="stocks",
                    universes=["large_cap"],
                    max_tickers=12,
                    reasoning_summary="Plan a stock scan.",
                ),
                planner_summary="Use a focused stock scan.",
            )
            return type("FakeResponse", (), {"output_parsed": parsed, "usage": {"input_tokens": 10, "output_tokens": 12}})()

    class FakeClient:
        responses = FakeResponses()

    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("OPENAI_PLANNER_MODEL", "gpt-test")
    monkeypatch.setattr(ai_planner, "_openai_sdk_available", lambda: True)
    monkeypatch.setattr(ai_planner, "_create_openai_client", lambda api_key, timeout: FakeClient())

    result = propose_scan_plan("Best stock ideas", provider="openai", request_id="req-3")

    assert result["ok"] is True
    assert result["status"] == "ai_planned"
    assert result["provider"] == "openai"
    assert result["model"] == "gpt-test"
    assert result["ai_available"] is True
    assert result["fallback_used"] is False
    assert captured["model"] == "gpt-test"
    assert captured["text_format"] is PlannerProposalModel
    assert result["approved_plan"]["max_tickers"] == 12
    assert result["usage"]["input_tokens"] == 10


def test_openai_failure_falls_back_to_deterministic(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setattr(ai_planner, "_openai_sdk_available", lambda: True)
    monkeypatch.setattr(ai_planner, "_create_openai_client", lambda api_key, timeout: (_ for _ in ()).throw(RuntimeError("boom")))

    result = propose_scan_plan("Best stock ideas", provider="openai", request_id="req-4")

    assert result["ok"] is True
    assert result["status"] == "deterministic_planned"
    assert result["fallback_used"] is True
    assert result["approved_plan"]["requested_instrument"] == "stocks"
    assert any("deterministic fallback" in warning.lower() for warning in result["warnings"])


def test_stock_only_message_overrides_ai_option_proposal(monkeypatch):
    class FakeResponses:
        def parse(self, **kwargs):
            parsed = {
                "intent": {"objective": "best_ideas", "requested_instrument": "options"},
                "proposed_plan": {
                    "requested_instrument": "options",
                    "objective": "options_research",
                    "include_options": True,
                    "prefer_options": True,
                    "universes": ["large_cap"],
                },
                "planner_summary": "Badly tried to include options.",
            }
            return type("FakeResponse", (), {"output_parsed": parsed, "usage": {}})()

    class FakeClient:
        responses = FakeResponses()

    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setattr(ai_planner, "_openai_sdk_available", lambda: True)
    monkeypatch.setattr(ai_planner, "_create_openai_client", lambda api_key, timeout: FakeClient())

    result = propose_scan_plan("Best stock ideas. Do stock only. Do not include options.", provider="openai", request_id="req-5")

    assert result["ok"] is True
    assert result["status"] == "ai_planned"
    assert result["intent"]["requested_instrument"] == "stocks"
    assert result["approved_plan"]["requested_instrument"] == "stocks"
    assert result["approved_plan"]["include_options"] is False
    assert result["approved_plan"]["prefer_options"] is False


def test_ai_cannot_add_custom_tickers_unless_user_names_them(monkeypatch):
    class FakeResponses:
        def parse(self, **kwargs):
            parsed = {
                "intent": {"objective": "best_ideas", "requested_instrument": "stocks"},
                "proposed_plan": {
                    "requested_instrument": "stocks",
                    "universes": ["custom"],
                    "custom_tickers": ["TSLA"],
                    "max_tickers": 1,
                },
                "planner_summary": "Invented a ticker.",
            }
            return type("FakeResponse", (), {"output_parsed": parsed, "usage": {}})()

    class FakeClient:
        responses = FakeResponses()

    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setattr(ai_planner, "_openai_sdk_available", lambda: True)
    monkeypatch.setattr(ai_planner, "_create_openai_client", lambda api_key, timeout: FakeClient())

    result = propose_scan_plan("Best stock ideas today", provider="openai", request_id="req-6")

    assert result["ok"] is True
    assert result["approved_plan"]["custom_tickers"] == []
    assert result["approved_plan"]["universes"] == ["large_cap"]


def test_explicit_ticker_review_preserves_named_ticker(monkeypatch):
    result = propose_scan_plan("Review AAPL", provider="deterministic", request_id="req-7")

    assert result["ok"] is True
    assert result["intent"]["objective"] == "ticker_review"
    assert result["approved_plan"]["custom_tickers"] == ["AAPL"]
    assert result["approved_plan"]["universes"] == ["custom"]


def test_system_question_does_not_force_an_invalid_scan_objective():
    result = propose_scan_plan("What is broken with the provider status?", provider="deterministic", request_id="req-8")

    assert result["ok"] is True
    assert result["intent"]["objective"] == "system_status"
    assert result["approved_plan"]["objective"] == "best_ideas"
    assert "no market scan should run" in result["planner_summary"].lower()


def test_research_language_enables_research_preferences():
    result = propose_scan_plan("Give me the best stocks and check current news.", provider="deterministic", request_id="req-9")

    research_preferences = result["approved_plan"]["research_preferences"]
    assert research_preferences["include_news"] is True
    assert research_preferences["include_sec_filings"] is False
    assert research_preferences["include_earnings_transcripts"] is False


def test_filing_and_earnings_language_enables_specific_research_preferences():
    result = propose_scan_plan("Review AAPL including filings and earnings.", provider="deterministic", request_id="req-10")

    research_preferences = result["approved_plan"]["research_preferences"]
    assert result["approved_plan"]["custom_tickers"] == ["AAPL"]
    assert research_preferences["include_news"] is False
    assert research_preferences["include_sec_filings"] is True
    assert research_preferences["include_earnings_transcripts"] is True


def test_technical_only_request_disables_current_research():
    result = propose_scan_plan("Do a technical-only stock scan.", provider="deterministic", request_id="req-11")

    research_preferences = result["approved_plan"]["research_preferences"]
    assert research_preferences["include_news"] is False
    assert research_preferences["include_sec_filings"] is False
    assert research_preferences["include_earnings_transcripts"] is False


def test_sanitized_context_and_preferences_do_not_expose_secrets(monkeypatch):
    context = ai_planner.sanitize_runtime_context(
        {
            "OPENAI_API_KEY": "sk-secret",
            "provider_status": "available",
            "market_regime": {"label": "risk_on", "raw_secret": "hidden"},
            "database_url": "sqlite:///secret",
            "option_quotes_validated": False,
        }
    )
    preferences = ai_planner.sanitize_user_preferences({"api_key": "secret", "risk_mode": "normal", "tickers": ["AAPL"]})

    assert context["provider_status"] == "available"
    assert context["market_regime"] == {"label": "risk_on"}
    assert "OPENAI_API_KEY" not in str(context)
    assert "secret" not in str(context)
    assert preferences == {"risk_mode": "normal", "tickers": ["AAPL"]}


def test_get_ai_planner_status_does_not_call_api(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setattr(ai_planner, "_openai_sdk_available", lambda: True)

    status = ai_planner.get_ai_planner_status(provider="auto")

    assert status["ai_planner_provider"] == "auto"
    assert status["openai_planner_configured"] is True
    assert status["openai_planner_sdk_available"] is True
    assert status["ai_planner_available"] is True
    assert os.getenv("OPENAI_API_KEY") not in str(status)
