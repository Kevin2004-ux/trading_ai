from macro.macro_risk import evaluate_macro_risk


def _event(event_type: str, importance: str, start: str, end: str, date: str | None = None) -> dict:
    return {
        "event_id": f"{event_type.lower()}-test",
        "date": date or start[:10],
        "event_type": event_type,
        "importance": importance,
        "risk_window": {
            "start": start,
            "end": end,
        },
    }


def test_critical_active_macro_window_blocks_new_trades():
    result = evaluate_macro_risk(
        as_of="2026-06-17T12:00:00",
        calendar=[
            _event(
                "FOMC",
                "critical",
                "2026-06-17T00:00:00",
                "2026-06-18T23:59:00",
                date="2026-06-18",
            )
        ],
    )

    assert result["ok"] is True
    assert result["macro_risk_level"] == "critical"
    assert result["new_trades_allowed"] is False
    assert result["risk_multiplier"] == 0.25
    assert result["warnings"]


def test_high_active_macro_window_reduces_risk_without_blocking():
    result = evaluate_macro_risk(
        as_of="2026-06-05T08:00:00",
        calendar=[_event("JOBS", "high", "2026-06-04T00:00:00", "2026-06-06T23:59:00")],
    )

    assert result["macro_risk_level"] == "high"
    assert result["new_trades_allowed"] is True
    assert result["risk_multiplier"] == 0.5


def test_macro_risk_disabled_returns_low_with_warning():
    result = evaluate_macro_risk(
        as_of="2026-06-17T12:00:00",
        calendar=[_event("FOMC", "critical", "2026-06-17T00:00:00", "2026-06-18T23:59:00")],
        config={"enabled": False},
    )

    assert result["macro_risk_level"] == "low"
    assert result["new_trades_allowed"] is True
    assert result["risk_multiplier"] == 1.0
