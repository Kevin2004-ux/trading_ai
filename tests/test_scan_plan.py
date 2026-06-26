from planning import SCAN_PLAN_VERSION, ScanPlan, build_default_scan_plan, validate_scan_plan


def test_scan_plan_defaults_are_safe_and_serializable():
    plan = ScanPlan()
    payload = plan.model_dump(mode="json")

    assert payload["plan_version"] == SCAN_PLAN_VERSION
    assert payload["requested_instrument"] == "stocks"
    assert payload["include_options"] is False
    assert payload["prefer_options"] is False
    assert payload["option_preferences"]["min_dte"] == 14


def test_default_best_stock_plan_uses_broader_scope_than_only_mega_cap():
    plan = build_default_scan_plan(objective="best_ideas", requested_instrument="stocks")
    result = validate_scan_plan(plan)

    assert result["ok"] is True
    assert result["approved_plan"]["requested_instrument"] == "stocks"
    assert result["execution_config"]["include_options"] is False
    assert result["execution_config"]["universes"] != ["mega_cap"]
    assert len(result["execution_config"]["universes"]) > 1
    assert any("Paper trading only" in rule for rule in result["immutable_rules"])


def test_default_option_plan_enables_options_research_not_execution():
    plan = build_default_scan_plan(objective="options_research", requested_instrument="options")
    result = validate_scan_plan(plan, runtime_context={"safe_to_run_options": False})

    assert result["approved_plan"]["requested_instrument"] == "options"
    assert result["execution_config"]["include_options"] is True
    assert result["execution_config"]["options_final_eligibility"] is False
    assert result["warnings"]


def test_ticker_review_default_plan_uses_custom_universe():
    plan = build_default_scan_plan(objective="ticker_review", requested_instrument="stocks", ticker="aapl")
    result = validate_scan_plan(plan)

    assert result["execution_config"]["universes"] == ["custom"]
    assert result["execution_config"]["custom_tickers"] == ["AAPL"]
    assert result["execution_config"]["max_tickers"] == 1
