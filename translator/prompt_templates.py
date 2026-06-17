from __future__ import annotations

import json
from typing import Any


CORE_RULES = """
You are the explanation layer for a deterministic swing-trading research system.
Paper trading/simulation only. You are not a financial advisor.

Hard rules:
- Use only facts from the provided tool/trading-brain result.
- Do not invent tickers, prices, scores, targets, stops, risk/reward, option contracts, macro events, news, filings, test results, or logging status.
- Do not say a trade was logged unless deterministic logged_count > 0 and the logged recommendation exists.
- Do not recommend options unless the deterministic option status is paper_eligible.
- Label options as research_only or blocked when that is the deterministic status.
- Explain rejected and watchlist candidates without upgrading them to final trades.
- Preserve warnings for historical fallback, stale data, partial scans, blocked options, critical news/filing risk, macro blocks, circuit breakers, concentration risk, startup readiness, and data quality.
- Never use certainty language such as guaranteed, sure thing, will profit, or can't lose.
- Never imply real brokerage execution, real orders, buy now, sell now, or order placement.
- Return structured JSON when requested.
"""


def _json_dumps(payload: Any) -> str:
    return json.dumps(payload, indent=2, sort_keys=True, default=str)


def build_gemini_system_prompt(config: dict | None = None) -> str:
    structured = bool((config or {}).get("structured_output", True))
    return (
        CORE_RULES.strip()
        + "\n\nOutput contract:\n"
        + (
            "Return valid JSON matching the requested response schema. Do not include markdown fences."
            if structured
            else "Return concise prose, but preserve every deterministic warning and paper-trading-only language."
        )
    )


def build_weekly_trade_hunt_prompt(
    user_request: str,
    trading_brain_result: dict,
    config: dict | None = None,
) -> str:
    return f"""
User request:
{user_request}

Task:
Format the deterministic weekly trade hunt result for the user.
Use response_type="weekly_trade_hunt".
Required fields: ok, response_type, paper_trading_only, market_context, final_paper_trades, watchlist, rejected_summary, options_status, risk_warnings, data_quality_warnings, plain_english_summary, errors.
Do not create any final_paper_trades that are not in decision_result.final_recommendations.

Deterministic trading-brain result:
{_json_dumps(trading_brain_result)}
""".strip()


def build_ticker_review_prompt(
    user_request: str,
    ticker_result: dict,
    config: dict | None = None,
) -> str:
    return f"""
User request:
{user_request}

Task:
Format the deterministic ticker review. Use response_type="ticker_review".
Do not upgrade rejected/watchlist status into a final recommendation.

Deterministic ticker result:
{_json_dumps(ticker_result)}
""".strip()


def build_paper_cycle_summary_prompt(
    paper_cycle_result: dict,
    config: dict | None = None,
) -> str:
    return f"""
Task:
Summarize the deterministic paper-trading cycle. Use response_type="paper_cycle_summary".
Paper trading only. Do not imply live brokerage P/L.
Do not say trades were logged unless summary.logged_count > 0.

Deterministic paper cycle result:
{_json_dumps(paper_cycle_result)}
""".strip()


def build_no_trade_prompt(
    trading_brain_result: dict,
    config: dict | None = None,
) -> str:
    return f"""
Task:
Explain that no final paper trade qualified. Use response_type="no_trade".
Include watchlist candidates and rejected reasons when present.
Preserve all risk and data-quality warnings.

Deterministic trading-brain result:
{_json_dumps(trading_brain_result)}
""".strip()
