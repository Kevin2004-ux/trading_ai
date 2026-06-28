from planning.intent_constraints import apply_intent_constraints_to_plan, extract_intent_constraints


def test_options_under_premium_with_upcoming_earnings_extracts_constraints():
    intent = extract_intent_constraints("Find me options under $250 premium with upcoming earnings")

    assert intent["requested_instrument"] == "options"
    assert intent["max_option_premium"] == 250
    assert intent["require_upcoming_earnings"] is True
    assert "earnings" in intent["catalyst_types"]
    assert intent["strategy_profile"] == "earnings_options"
    assert intent["external_discovery_requested"] is True


def test_small_cap_under_10_aggressive_extracts_constraints():
    intent = extract_intent_constraints("Find aggressive small cap stocks under $10")

    assert intent["requested_instrument"] == "stocks"
    assert intent["max_stock_price"] == 10
    assert intent["allow_small_cap"] is True
    assert intent["risk_style"] == "aggressive"
    assert intent["strategy_profile"] == "small_cap_momentum"


def test_apply_intent_constraints_passes_option_preferences_and_keeps_safety_scope():
    intent = extract_intent_constraints("options under $250 with upcoming earnings")
    plan = apply_intent_constraints_to_plan(
        {
            "requested_instrument": "stocks",
            "include_options": False,
            "prefer_options": False,
            "option_preferences": {"min_dte": 14, "max_dte": 56},
        },
        intent,
    )

    assert plan["requested_instrument"] == "options"
    assert plan["include_options"] is True
    assert plan["prefer_options"] is True
    assert plan["option_preferences"]["max_option_premium"] == 250
    assert plan["include_catalysts"] is True
    assert plan["user_intent"]["require_upcoming_earnings"] is True


def test_stock_only_intent_disables_options_when_terms_conflict():
    intent = extract_intent_constraints("Give me best stocks only, no options")
    plan = apply_intent_constraints_to_plan(
        {"requested_instrument": "both", "include_options": True, "prefer_options": True},
        intent,
    )

    assert intent["requested_instrument"] == "stocks"
    assert plan["include_options"] is False
    assert plan["prefer_options"] is False
