from __future__ import annotations

from typing import Any

from risk.concentration_controls import evaluate_concentration_risk
from simulation.scenario_definitions import get_stress_scenario
from simulation.stress_engine import run_stress_test_on_candidate
from tracking.trade_logger import get_open_recommendations


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _trade_loss_r(trade: dict, scenario: dict) -> float:
    stressed = run_stress_test_on_candidate(trade, scenario)
    drawdown = _safe_float(stressed.get("risk_impact", {}).get("estimated_drawdown_r"), -1.0)
    return drawdown


def estimate_portfolio_stress_loss(
    open_trades: list[dict],
    scenario: dict,
    correlation_matrix: dict | None = None,
    config: dict | None = None,
) -> dict:
    trades = [trade for trade in open_trades or [] if isinstance(trade, dict)]
    losses = [
        {
            "ticker": trade.get("ticker"),
            "setup_type": trade.get("setup_type"),
            "estimated_loss_r": _trade_loss_r(trade, scenario),
            "risk_reward": trade.get("risk_reward"),
        }
        for trade in trades
    ]
    total_loss_r = round(sum(_safe_float(item["estimated_loss_r"]) for item in losses), 4)
    account_size = _safe_float((config or {}).get("account_size"), 10000.0)
    risk_per_trade_percent = _safe_float((config or {}).get("risk_per_trade_percent"), 1.0)
    total_loss_percent = round(abs(total_loss_r) * risk_per_trade_percent, 4)
    concentration = evaluate_concentration_risk(
        trades[0],
        open_trades=trades[1:],
        correlation_matrix=correlation_matrix,
    ) if trades else {"ok": True, "approved": True, "risk_level": "low", "reasons": []}
    threshold = _safe_float((config or {}).get("max_acceptable_loss_r"), _safe_float((config or {}).get("STRESS_MAX_ACCEPTABLE_LOSS_R"), 3.0))
    warnings = []
    if abs(total_loss_r) > threshold:
        warnings.append(f"Estimated stress loss {total_loss_r}R exceeds threshold {threshold}R.")
    return {
        "ok": True,
        "open_trade_count": len(trades),
        "estimated_total_loss_r": total_loss_r,
        "estimated_total_loss_percent": total_loss_percent,
        "account_size": account_size,
        "worst_affected_trades": sorted(losses, key=lambda item: item["estimated_loss_r"])[:5],
        "concentration_risk": concentration,
        "scenario": scenario,
        "warnings": warnings,
        "errors": [],
    }


def stress_test_open_paper_trades(
    db_path: str,
    scenario_name: str,
    config: dict | None = None,
) -> dict:
    scenario_result = get_stress_scenario(scenario_name)
    if not scenario_result.get("ok"):
        return {
            "ok": False,
            "open_trade_count": 0,
            "estimated_total_loss_r": None,
            "estimated_total_loss_percent": None,
            "worst_affected_trades": [],
            "concentration_risk": {},
            "scenario": None,
            "warnings": [],
            "errors": scenario_result.get("errors", []),
        }
    open_trades = get_open_recommendations(db_path=db_path)
    if isinstance(open_trades, dict) and open_trades.get("ok") is False:
        return {
            "ok": False,
            "open_trade_count": 0,
            "estimated_total_loss_r": None,
            "estimated_total_loss_percent": None,
            "worst_affected_trades": [],
            "concentration_risk": {},
            "scenario": scenario_result["scenario"],
            "warnings": [],
            "errors": [open_trades.get("error", "Failed to load open paper trades.")],
        }
    return estimate_portfolio_stress_loss(
        open_trades if isinstance(open_trades, list) else [],
        scenario_result["scenario"],
        config=config,
    )
