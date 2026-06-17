from __future__ import annotations

from collections import defaultdict
from typing import Any

from analytics.performance_attribution import analyze_paper_trade_performance
from analytics.setup_decay import evaluate_all_setup_decay


def _safe_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _setup_status(metrics: dict, config: dict) -> tuple[str, list[str], list[str]]:
    sample = int(metrics.get("closed_trade_count") or 0)
    expectancy = _safe_float(metrics.get("expectancy_r"))
    win_rate = _safe_float(metrics.get("win_rate"))
    min_sample = int(config.get("minimum_sample_size", 8))
    disabled_sample = int(config.get("disabled_sample_size", 15))
    severe_threshold = float(config.get("disabled_expectancy_threshold_r", -0.6))
    reasons: list[str] = []
    warnings: list[str] = []

    if sample < min_sample:
        reasons.append("Fewer than 8 closed paper trades; treat this setup as watch/insufficient sample.")
        warnings.append("Small sample; do not claim setup edge yet.")
        return "watch", reasons, warnings
    if expectancy is not None and sample >= disabled_sample and expectancy <= severe_threshold:
        reasons.append(f"Expectancy {expectancy}R is severely negative over {sample} closed paper trades.")
        warnings.append("Disabled-candidate diagnostic only; existing setup-decay controls must approve any hard disable.")
        return "disabled_candidate", reasons, warnings
    if expectancy is not None and expectancy < 0:
        reasons.append(f"Expectancy {expectancy}R is negative over a usable sample.")
        warnings.append("Setup appears to be decaying; review filters before taking new paper candidates.")
        return "decaying", reasons, warnings
    if expectancy is not None and expectancy >= 0.4 and win_rate is not None and win_rate >= 55:
        reasons.append("Positive expectancy and stable win rate over a usable sample.")
        return "strong", reasons, warnings
    if expectancy is not None and expectancy >= 0:
        reasons.append("Positive or break-even expectancy over a usable sample.")
        return "healthy", reasons, warnings
    reasons.append("Not enough R-multiple data to classify confidently.")
    warnings.append("Setup health is uncertain.")
    return "watch", reasons, warnings


def analyze_setup_performance(
    trades: list[dict],
    setup_field: str = "setup_type",
    config: dict | None = None,
) -> dict:
    cfg = dict(config or {})
    grouped: dict[str, list[dict]] = defaultdict(list)
    for trade in trades or []:
        if isinstance(trade, dict):
            setup = str(trade.get(setup_field) or trade.get("strategy") or "unspecified")
            grouped[setup].append(trade)

    setups: list[dict] = []
    for setup, rows in grouped.items():
        perf = analyze_paper_trade_performance(rows, config={"min_closed_trades": cfg.get("minimum_sample_size", 8)})
        status, reasons, warnings = _setup_status(perf, cfg)
        setups.append(
            {
                "setup_type": setup,
                "trade_count": perf["trade_count"],
                "closed_trade_count": perf["closed_trade_count"],
                "win_rate": perf["win_rate"],
                "expectancy_r": perf["expectancy_r"],
                "profit_factor": perf["profit_factor"],
                "avg_hold_days": perf["median_hold_days"],
                "status": status,
                "reasons": reasons,
                "warnings": warnings + list(perf.get("warnings", [])),
            }
        )
    status_rank = {"strong": 0, "healthy": 1, "watch": 2, "decaying": 3, "disabled_candidate": 4}
    setups.sort(key=lambda item: (status_rank.get(item["status"], 5), -(item.get("closed_trade_count") or 0), item["setup_type"]))
    return {
        "ok": True,
        "setups": setups,
        "overall_status": "no_data" if not setups else ("degraded" if any(item["status"] in {"decaying", "disabled_candidate"} for item in setups) else "healthy_or_watch"),
        "recommendations": _recommendations(setups),
        "warnings": [warning for item in setups for warning in item.get("warnings", [])],
    }


def _recommendations(setups: list[dict]) -> list[str]:
    recommendations: list[str] = []
    for setup in setups:
        status = setup.get("status")
        name = setup.get("setup_type")
        if status == "disabled_candidate":
            recommendations.append(f"{name}: review as disabled-candidate, but do not disable without setup-decay approval.")
        elif status == "decaying":
            recommendations.append(f"{name}: review recent losers, filters, and market-regime fit before adding risk.")
        elif status == "watch":
            recommendations.append(f"{name}: collect more closed paper trades before drawing conclusions.")
    return recommendations


def diagnose_strategy_health(
    trades: list[dict],
    config: dict | None = None,
) -> dict:
    setup_result = analyze_setup_performance(trades, config=config)
    decay_context = evaluate_all_setup_decay(trades, config=config)
    setups = setup_result.get("setups", [])
    disabled = [item for item in setups if item.get("status") == "disabled_candidate"]
    decaying = [item for item in setups if item.get("status") == "decaying"]
    strong = [item for item in setups if item.get("status") == "strong"]
    if disabled:
        overall_status = "critical_review"
    elif decaying:
        overall_status = "degrading"
    elif strong:
        overall_status = "improving"
    elif setups:
        overall_status = "stable_or_insufficient_sample"
    else:
        overall_status = "no_data"
    return {
        "ok": True,
        "setups": setups,
        "overall_status": overall_status,
        "setup_decay_context": decay_context,
        "recommendations": setup_result.get("recommendations", []),
        "warnings": setup_result.get("warnings", []),
    }
