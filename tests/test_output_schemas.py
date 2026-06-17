from translator.output_schemas import (
    validate_schema_shape,
    validation_issue,
    weekly_trade_hunt_response,
)


def test_weekly_trade_hunt_response_has_required_shape():
    payload = weekly_trade_hunt_response(
        market_context={"regime": "risk_on"},
        final_paper_trades=[{"ticker": "AAPL"}],
        plain_english_summary="Paper trading only.",
    )

    assert payload["ok"] is True
    assert payload["response_type"] == "weekly_trade_hunt"
    assert payload["paper_trading_only"] is True
    assert validate_schema_shape(payload) == []


def test_schema_validation_catches_missing_required_fields():
    issues = validate_schema_shape({"response_type": "weekly_trade_hunt", "paper_trading_only": True})

    assert any(issue["code"] == "missing_required_field" for issue in issues)


def test_schema_validation_requires_paper_trading_flag():
    payload = weekly_trade_hunt_response()
    payload["paper_trading_only"] = False

    issues = validate_schema_shape(payload)

    assert any(issue["code"] == "missing_paper_disclaimer" for issue in issues)


def test_validation_issue_shape():
    issue = validation_issue("blocking", "bad_output", "Bad output", "$.field")

    assert issue == {
        "severity": "blocking",
        "code": "bad_output",
        "message": "Bad output",
        "path": "$.field",
    }
