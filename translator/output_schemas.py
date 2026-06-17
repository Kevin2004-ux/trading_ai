from __future__ import annotations

from typing import Any


WEEKLY_TRADE_HUNT_REQUIRED_FIELDS = {
    "ok",
    "response_type",
    "paper_trading_only",
    "market_context",
    "final_paper_trades",
    "watchlist",
    "rejected_summary",
    "options_status",
    "risk_warnings",
    "data_quality_warnings",
    "plain_english_summary",
    "errors",
}

VALID_RESPONSE_TYPES = {
    "weekly_trade_hunt",
    "ticker_review",
    "paper_cycle_summary",
    "no_trade",
}


def validation_issue(
    severity: str,
    code: str,
    message: str,
    path: str = "$",
) -> dict:
    return {
        "severity": severity,
        "code": code,
        "message": message,
        "path": path,
    }


def validated_output(
    ok: bool,
    validation_status: str,
    safe_to_show_user: bool,
    safe_to_log: bool,
    issues: list[dict] | None = None,
    normalized_output: dict | None = None,
    repair_suggestions: list[str] | None = None,
    warnings: list[str] | None = None,
    errors: list[str] | None = None,
) -> dict:
    return {
        "ok": bool(ok),
        "validation_status": validation_status,
        "safe_to_show_user": bool(safe_to_show_user),
        "safe_to_log": bool(safe_to_log),
        "issues": issues or [],
        "normalized_output": normalized_output,
        "repair_suggestions": repair_suggestions or [],
        "warnings": warnings or [],
        "errors": errors or [],
    }


def trade_idea_explanation(**kwargs: Any) -> dict:
    return {
        "ticker": kwargs.get("ticker"),
        "asset_type": kwargs.get("asset_type", "stock"),
        "direction": kwargs.get("direction"),
        "entry_price": kwargs.get("entry_price"),
        "target_price": kwargs.get("target_price"),
        "stop_loss": kwargs.get("stop_loss"),
        "risk_reward": kwargs.get("risk_reward"),
        "paper_logged": bool(kwargs.get("paper_logged", False)),
        "option_status": kwargs.get("option_status"),
        "why_it_passed": kwargs.get("why_it_passed", []),
        "risks": kwargs.get("risks", []),
    }


def weekly_trade_hunt_response(
    *,
    ok: bool = True,
    market_context: dict | None = None,
    final_paper_trades: list[dict] | None = None,
    watchlist: list[dict] | None = None,
    rejected_summary: list[dict] | None = None,
    options_status: dict | None = None,
    risk_warnings: list[str] | None = None,
    data_quality_warnings: list[str] | None = None,
    plain_english_summary: str = "",
    errors: list[str] | None = None,
) -> dict:
    return {
        "ok": bool(ok),
        "response_type": "weekly_trade_hunt",
        "paper_trading_only": True,
        "market_context": market_context or {},
        "final_paper_trades": final_paper_trades or [],
        "watchlist": watchlist or [],
        "rejected_summary": rejected_summary or [],
        "options_status": options_status or {},
        "risk_warnings": risk_warnings or [],
        "data_quality_warnings": data_quality_warnings or [],
        "plain_english_summary": plain_english_summary,
        "errors": errors or [],
    }


def ticker_review_response(**kwargs: Any) -> dict:
    return {
        "ok": bool(kwargs.get("ok", True)),
        "response_type": "ticker_review",
        "paper_trading_only": True,
        "ticker": kwargs.get("ticker"),
        "status": kwargs.get("status"),
        "trade": kwargs.get("trade"),
        "watchlist_reasons": kwargs.get("watchlist_reasons", []),
        "rejection_reasons": kwargs.get("rejection_reasons", []),
        "risk_warnings": kwargs.get("risk_warnings", []),
        "plain_english_summary": kwargs.get("plain_english_summary", ""),
        "errors": kwargs.get("errors", []),
    }


def paper_cycle_summary_response(**kwargs: Any) -> dict:
    return {
        "ok": bool(kwargs.get("ok", True)),
        "response_type": "paper_cycle_summary",
        "paper_trading_only": True,
        "selected_count": kwargs.get("selected_count", 0),
        "logged_count": kwargs.get("logged_count", 0),
        "paper_trades_logged": kwargs.get("paper_trades_logged", []),
        "risk_warnings": kwargs.get("risk_warnings", []),
        "plain_english_summary": kwargs.get("plain_english_summary", ""),
        "errors": kwargs.get("errors", []),
    }


def no_trade_response(**kwargs: Any) -> dict:
    return {
        "ok": bool(kwargs.get("ok", True)),
        "response_type": "no_trade",
        "paper_trading_only": True,
        "reason": kwargs.get("reason", ""),
        "watchlist": kwargs.get("watchlist", []),
        "rejected_summary": kwargs.get("rejected_summary", []),
        "risk_warnings": kwargs.get("risk_warnings", []),
        "plain_english_summary": kwargs.get("plain_english_summary", ""),
        "errors": kwargs.get("errors", []),
    }


def validate_schema_shape(payload: dict) -> list[dict]:
    issues: list[dict] = []
    if not isinstance(payload, dict):
        return [validation_issue("blocking", "schema_not_object", "Gemini output must be a JSON object.")]
    response_type = payload.get("response_type")
    if response_type not in VALID_RESPONSE_TYPES:
        issues.append(validation_issue("blocking", "invalid_response_type", "Unsupported or missing response_type.", "$.response_type"))
    if response_type == "weekly_trade_hunt":
        missing = sorted(WEEKLY_TRADE_HUNT_REQUIRED_FIELDS - set(payload))
        for field in missing:
            issues.append(validation_issue("blocking", "missing_required_field", f"Missing required field: {field}", f"$.{field}"))
    if payload.get("paper_trading_only") is not True:
        issues.append(validation_issue("blocking", "missing_paper_disclaimer", "paper_trading_only must be true.", "$.paper_trading_only"))
    return issues
