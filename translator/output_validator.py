from __future__ import annotations

import json
import re
from typing import Any

from .grounding import check_claim_against_grounding, extract_grounding_facts
from .output_schemas import validate_schema_shape, validated_output, validation_issue


CERTAINTY_PATTERNS = [
    r"\bguaranteed\b",
    r"\bsure thing\b",
    r"\bwill profit\b",
    r"\bcan't lose\b",
    r"\bcannot lose\b",
]
ORDER_PATTERNS = [
    r"\bplace (?:a )?(?:real )?order\b",
    r"\bexecuted\b",
    r"\bbuy now\b",
    r"\bsell now\b",
    r"\bsubmit order\b",
    r"\bsent to broker\b",
]


def _parse_output(gemini_output: dict | str) -> tuple[dict | None, list[dict]]:
    if isinstance(gemini_output, dict):
        return gemini_output, []
    if not isinstance(gemini_output, str):
        return None, [validation_issue("blocking", "invalid_output_type", "Gemini output must be a dict or JSON string.")]
    text = gemini_output.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?", "", text).strip()
        text = re.sub(r"```$", "", text).strip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        return None, [validation_issue("blocking", "json_parse_failed", f"Output is not valid JSON: {exc}")]
    if not isinstance(parsed, dict):
        return None, [validation_issue("blocking", "json_not_object", "Structured Gemini output must be a JSON object.")]
    return parsed, []


def _all_text(payload: Any) -> str:
    if isinstance(payload, dict):
        return " ".join(_all_text(value) for value in payload.values())
    if isinstance(payload, list):
        return " ".join(_all_text(value) for value in payload)
    return str(payload or "")


def _safe_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _ticker(value: Any) -> str:
    return str(value or "").strip().upper()


def _mentions_affirmative_logging(text: str) -> bool:
    lowered = str(text or "").lower()
    if not re.search(r"\b(logged|tracked)\b", lowered):
        return False
    negated_patterns = [
        r"\bno\b[^.]{0,60}\b(logged|tracked)\b",
        r"\bnot\b[^.]{0,60}\b(logged|tracked)\b",
        r"\bzero\b[^.]{0,60}\b(logged|tracked)\b",
        r"\b0\b[^.]{0,60}\b(logged|tracked)\b",
        r"\b(logged|tracked)\b[^.]{0,60}\b(no|not|zero|0)\b",
    ]
    return not any(re.search(pattern, lowered) for pattern in negated_patterns)


def _validate_common(payload: dict, facts: dict) -> list[dict]:
    issues = validate_schema_shape(payload)
    text = _all_text(payload).lower()
    for pattern in CERTAINTY_PATTERNS:
        if re.search(pattern, text):
            issues.append(validation_issue("blocking", "certainty_language", "Output contains prohibited certainty/profit language."))
            break
    for pattern in ORDER_PATTERNS:
        if re.search(pattern, text):
            issues.append(validation_issue("blocking", "real_order_language", "Output implies real brokerage execution or order placement."))
            break
    if "paper" not in text and "simulation" not in text and "simulated" not in text:
        issues.append(validation_issue("blocking", "missing_paper_language", "Output must clearly say paper trading/simulation only."))
    allowed = set(facts.get("allowed_tickers", []))
    for match in re.findall(r"\b[A-Z]{1,5}(?:\.[A-Z])?\b", _all_text(payload)):
        if match in {"USD", "ETF", "SEC", "API", "P/L", "IV", "DTE", "CEO", "CFO", "DOJ", "FDA"}:
            continue
        if allowed and match not in allowed and match in text.upper():
            issues.append(validation_issue("error", "possibly_ungrounded_ticker", f"{match} is not present in deterministic results."))
    return issues


def validate_weekly_trade_hunt_response(payload: dict, trading_brain_result: dict, config: dict | None = None) -> dict:
    facts = extract_grounding_facts(trading_brain_result)
    issues = _validate_common(payload, facts)
    selected = set(facts.get("selected_tickers", []))
    logged = set(facts.get("logged_tickers", []))
    selected_count = facts.get("selected_count", 0)
    logged_count = facts.get("logged_count", 0)

    final_trades = payload.get("final_paper_trades", [])
    if not isinstance(final_trades, list):
        issues.append(validation_issue("blocking", "final_trades_not_list", "final_paper_trades must be a list.", "$.final_paper_trades"))
        final_trades = []
    if selected_count == 0 and final_trades:
        issues.append(validation_issue("blocking", "fabricated_trade_when_none_selected", "No deterministic trades were selected, but output includes final trades."))

    for index, trade in enumerate(final_trades):
        if not isinstance(trade, dict):
            issues.append(validation_issue("blocking", "trade_not_object", "Final paper trade must be an object.", f"$.final_paper_trades[{index}]"))
            continue
        ticker = _ticker(trade.get("ticker"))
        if ticker not in selected:
            issues.append(validation_issue("blocking", "fabricated_final_trade", f"{ticker} was not selected by the deterministic engine.", f"$.final_paper_trades[{index}].ticker"))
        claim_check = check_claim_against_grounding(trade, facts)
        if not claim_check.get("ok"):
            issues.append(validation_issue("blocking", claim_check["code"], claim_check["message"], f"$.final_paper_trades[{index}]"))
        if trade.get("paper_logged") is True and ticker not in logged:
            issues.append(validation_issue("blocking", "fabricated_logged_trade", f"{ticker} was not logged by the deterministic engine.", f"$.final_paper_trades[{index}].paper_logged"))
        preferred_instrument = str(trade.get("preferred_instrument") or trade.get("asset_type") or "").lower()
        option_status = str(trade.get("option_status") or trade.get("options_status") or "").lower()
        if preferred_instrument == "option" and option_status != "paper_eligible":
            issues.append(validation_issue("blocking", "unsupported_option_recommendation", "Options may only be recommended when paper_eligible.", f"$.final_paper_trades[{index}]"))

    if logged_count == 0 and _mentions_affirmative_logging(_all_text(payload)):
        issues.append(validation_issue("blocking", "fabricated_logging_status", "Output says a trade was logged/tracked but deterministic logged_count is 0."))

    options_status_text = _all_text(payload.get("options_status", {})).lower()
    option_facts = facts.get("options_status", {})
    if option_facts.get("blocked_or_research_only") and "blocked" not in options_status_text and "research" not in options_status_text and option_facts.get("options_included"):
        issues.append(validation_issue("error", "missing_options_blocked_status", "Blocked/research-only option status must be preserved.", "$.options_status"))

    required_warnings = facts.get("data_quality_warnings", [])
    output_warning_text = _all_text(payload.get("data_quality_warnings", [])).lower()
    for warning in required_warnings:
        lowered = str(warning).lower()
        if any(token in lowered for token in ("fallback", "stale", "partial")) and lowered[:24] not in output_warning_text:
            issues.append(validation_issue("error", "missing_data_quality_warning", f"Missing data quality warning: {warning}", "$.data_quality_warnings"))

    return _finalize(payload, issues)


def validate_ticker_review_response(payload: dict, trading_brain_result: dict, config: dict | None = None) -> dict:
    facts = extract_grounding_facts({"decision_result": {"final_recommendations": [trading_brain_result.get("decision", {})]}, "summary": {}})
    issues = _validate_common(payload, facts)
    return _finalize(payload, issues)


def validate_paper_cycle_summary_response(payload: dict, trading_brain_result: dict, config: dict | None = None) -> dict:
    facts = extract_grounding_facts(trading_brain_result.get("trade_hunt", trading_brain_result) if isinstance(trading_brain_result, dict) else {})
    issues = _validate_common(payload, facts)
    logged_count = ((trading_brain_result.get("summary") or {}).get("logged_count") if isinstance(trading_brain_result, dict) else None) or facts.get("logged_count", 0)
    if logged_count == 0 and _mentions_affirmative_logging(_all_text(payload)):
        issues.append(validation_issue("blocking", "fabricated_logging_status", "Output says trades were logged but deterministic logged_count is 0."))
    return _finalize(payload, issues)


def _finalize(payload: dict | None, issues: list[dict]) -> dict:
    blocking = [issue for issue in issues if issue.get("severity") == "blocking"]
    errors = [issue for issue in issues if issue.get("severity") == "error"]
    status = "fail" if blocking else "warn" if errors or issues else "pass"
    return validated_output(
        ok=not blocking,
        validation_status=status,
        safe_to_show_user=not blocking,
        safe_to_log=False,
        issues=issues,
        normalized_output=payload if not blocking else None,
        repair_suggestions=[
            "Use only tickers, prices, risk/reward, warnings, and logging status from the deterministic trading-brain result.",
            "Preserve paper-trading-only language and blocked/research-only option status.",
        ]
        if blocking or errors
        else [],
        warnings=[issue["message"] for issue in issues if issue.get("severity") == "warning"],
        errors=[issue["message"] for issue in blocking + errors],
    )


def validate_gemini_output(
    gemini_output: dict | str,
    trading_brain_result: dict,
    config: dict | None = None,
) -> dict:
    payload, parse_issues = _parse_output(gemini_output)
    if parse_issues:
        return _finalize(None, parse_issues)
    response_type = str((payload or {}).get("response_type", "weekly_trade_hunt"))
    if response_type == "weekly_trade_hunt":
        return validate_weekly_trade_hunt_response(payload, trading_brain_result, config=config)
    if response_type == "ticker_review":
        return validate_ticker_review_response(payload, trading_brain_result, config=config)
    if response_type == "paper_cycle_summary":
        return validate_paper_cycle_summary_response(payload, trading_brain_result, config=config)
    return _finalize(payload, _validate_common(payload or {}, extract_grounding_facts(trading_brain_result)))
