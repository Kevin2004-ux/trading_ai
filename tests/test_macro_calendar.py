from macro.calendar import classify_macro_event_importance, get_macro_calendar


def test_static_macro_calendar_returns_expected_schema():
    result = get_macro_calendar(start_date="2026-06-01", end_date="2026-06-30")

    assert result["ok"] is True
    assert result["source"] == "static"
    assert result["events"]
    event = result["events"][0]
    assert {"event_id", "date", "event_type", "importance", "risk_window"} <= set(event)
    assert {"start", "end"} <= set(event["risk_window"])


def test_classifies_cpi_and_fomc_as_critical():
    cpi = classify_macro_event_importance({"event_id": "cpi", "event_type": "CPI"})
    fomc = classify_macro_event_importance({"event_id": "fomc", "event_type": "FOMC"})

    assert cpi["importance"] == "critical"
    assert cpi["risk_score"] == 4
    assert fomc["importance"] == "critical"


def test_invalid_calendar_range_returns_clean_error():
    result = get_macro_calendar(start_date="2026-06-30", end_date="2026-06-01")

    assert result["ok"] is False
    assert result["events"] == []
    assert "end_date" in result["error"]
