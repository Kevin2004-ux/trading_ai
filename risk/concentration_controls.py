from __future__ import annotations

from datetime import datetime, timezone
import os
from typing import Any

from risk.portfolio_manager import calculate_trade_risk


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _bool_env(name: str, default: bool) -> bool:
    return str(os.getenv(name, str(default))).strip().lower() in {"1", "true", "yes", "on"}


def _float_env(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


def _config(config: dict | None = None) -> dict:
    normalized = {
        "enabled": _bool_env("CORRELATION_ENABLED", True),
        "max_single_ticker_exposure": _float_env("MAX_SINGLE_TICKER_EXPOSURE", 0.15),
        "max_sector_exposure": _float_env("MAX_SECTOR_EXPOSURE", 0.40),
        "max_correlated_cluster_exposure": _float_env("MAX_CORRELATED_CLUSTER_EXPOSURE", 0.50),
        "high_correlation_threshold": _float_env("HIGH_CORRELATION_THRESHOLD", 0.85),
        "moderate_correlation_threshold": _float_env("MODERATE_CORRELATION_THRESHOLD", 0.75),
        "max_total_open_risk_percent": 0.05,
        "account_size": 10000.0,
    }
    if isinstance(config, dict):
        normalized.update(config)
    return normalized


def _safe_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _ticker(trade: dict) -> str:
    source_candidate = trade.get("source_candidate") if isinstance(trade.get("source_candidate"), dict) else {}
    if str(trade.get("asset_type", "")).lower() == "option" or trade.get("option_contract"):
        return str(trade.get("underlying_ticker") or source_candidate.get("underlying_ticker") or trade.get("ticker") or "").upper()
    return str(trade.get("ticker") or source_candidate.get("ticker") or "").upper()


def _sector(trade: dict) -> str:
    source_candidate = trade.get("source_candidate") if isinstance(trade.get("source_candidate"), dict) else {}
    return str(
        trade.get("sector")
        or trade.get("industry_sector")
        or source_candidate.get("sector")
        or source_candidate.get("industry_sector")
        or "unknown"
    ).strip().lower() or "unknown"


def _direction(trade: dict) -> str:
    source_candidate = trade.get("source_candidate") if isinstance(trade.get("source_candidate"), dict) else {}
    return str(trade.get("direction") or source_candidate.get("direction") or "long").lower()


def _risk_percent(trade: dict, cfg: dict) -> float:
    sizing = trade.get("position_sizing") if isinstance(trade.get("position_sizing"), dict) else {}
    estimated_loss = _safe_float(sizing.get("estimated_max_loss"))
    account_size = _safe_float(cfg.get("account_size")) or 10000.0
    if estimated_loss is not None and account_size > 0:
        return estimated_loss / account_size
    risk = calculate_trade_risk(trade, account_size=account_size, config={"account_size": account_size})
    return _safe_float(risk.get("risk_percent_of_account")) or 0.0


def _correlation(left: str, right: str, matrix: dict | None) -> float | None:
    if not isinstance(matrix, dict):
        return None
    correlations = matrix.get("correlations") if "correlations" in matrix else matrix.get("matrix_json")
    if not isinstance(correlations, dict):
        return None
    left = left.upper()
    right = right.upper()
    value = None
    if isinstance(correlations.get(left), dict):
        value = correlations[left].get(right)
    if value is None and isinstance(correlations.get(right), dict):
        value = correlations[right].get(left)
    return _safe_float(value)


def _base_response(
    *,
    approved: bool,
    risk_level: str,
    concentration_score: float,
    correlated_exposure: dict,
    sector_exposure: dict,
    ticker_overlap: list[str],
    risk_multiplier: float,
    reasons: list[str],
    warnings: list[str],
) -> dict:
    return {
        "ok": True,
        "timestamp": _now_iso(),
        "approved": approved,
        "risk_level": risk_level,
        "concentration_score": round(concentration_score, 2),
        "correlated_exposure": correlated_exposure,
        "sector_exposure": sector_exposure,
        "ticker_overlap": ticker_overlap,
        "risk_multiplier": round(risk_multiplier, 4),
        "reasons": reasons,
        "warnings": warnings,
    }


def evaluate_concentration_risk(
    candidate_trade: dict,
    open_trades: list[dict],
    correlation_matrix: dict | None = None,
    config: dict | None = None,
) -> dict:
    cfg = _config(config)
    warnings: list[str] = []
    reasons: list[str] = []
    if not cfg["enabled"]:
        return _base_response(
            approved=True,
            risk_level="low",
            concentration_score=0.0,
            correlated_exposure={},
            sector_exposure={},
            ticker_overlap=[],
            risk_multiplier=1.0,
            reasons=["Correlation controls are disabled."],
            warnings=["Correlation controls are disabled."],
        )

    if not isinstance(candidate_trade, dict):
        return _base_response(
            approved=False,
            risk_level="blocked",
            concentration_score=100.0,
            correlated_exposure={},
            sector_exposure={},
            ticker_overlap=[],
            risk_multiplier=0.0,
            reasons=["Candidate trade is invalid."],
            warnings=[],
        )

    candidate_ticker = _ticker(candidate_trade)
    candidate_sector = _sector(candidate_trade)
    candidate_direction = _direction(candidate_trade)
    candidate_risk = _risk_percent(candidate_trade, cfg)
    open_items = [trade for trade in (open_trades or []) if isinstance(trade, dict)]

    ticker_overlap = sorted({_ticker(trade) for trade in open_items if _ticker(trade) and _ticker(trade) == candidate_ticker})
    sector_risk_existing = sum(_risk_percent(trade, cfg) for trade in open_items if _sector(trade) == candidate_sector and candidate_sector != "unknown")
    ticker_risk_existing = sum(_risk_percent(trade, cfg) for trade in open_items if _ticker(trade) == candidate_ticker)
    total_open_risk = sum(_risk_percent(trade, cfg) for trade in open_items)
    sector_total = sector_risk_existing + candidate_risk
    ticker_total = ticker_risk_existing + candidate_risk
    total_if_added = total_open_risk + candidate_risk

    high_correlations: list[dict] = []
    moderate_correlations: list[dict] = []
    if correlation_matrix is None and open_items:
        warnings.append("Correlation matrix unavailable; applying conservative concentration multiplier.")
        reasons.append("Correlation data unavailable.")
    for trade in open_items:
        open_ticker = _ticker(trade)
        if not open_ticker or not candidate_ticker:
            continue
        corr = _correlation(candidate_ticker, open_ticker, correlation_matrix)
        if corr is None:
            continue
        item = {
            "ticker": open_ticker,
            "correlation": corr,
            "same_direction": _direction(trade) == candidate_direction,
            "risk_percent": _risk_percent(trade, cfg),
        }
        if corr > float(cfg["high_correlation_threshold"]):
            high_correlations.append(item)
        if corr > float(cfg["moderate_correlation_threshold"]):
            moderate_correlations.append(item)

    correlated_cluster_exposure = candidate_risk + sum(item["risk_percent"] for item in moderate_correlations)
    approved = True
    risk_level = "low"
    risk_multiplier = 1.0
    concentration_score = 0.0

    if ticker_total > float(cfg["max_single_ticker_exposure"]):
        approved = False
        risk_level = "blocked"
        risk_multiplier = 0.0
        reasons.append("Single ticker exposure would exceed configured maximum.")
        concentration_score += 100

    if total_if_added > float(cfg["max_total_open_risk_percent"]):
        approved = False
        risk_level = "blocked"
        risk_multiplier = 0.0
        reasons.append("Total portfolio open risk would exceed configured maximum.")
        concentration_score += 75

    same_direction_high = [item for item in high_correlations if item["same_direction"]]
    if same_direction_high and approved:
        risk_level = "high"
        risk_multiplier = min(risk_multiplier, 0.5)
        reasons.append("Candidate is highly correlated with an open trade in the same direction.")
        concentration_score += 35

    if len(moderate_correlations) >= 2 and approved:
        if correlated_cluster_exposure > float(cfg["max_correlated_cluster_exposure"]):
            approved = False
            risk_level = "blocked"
            risk_multiplier = 0.0
            reasons.append("Correlated cluster exposure would exceed configured maximum.")
            concentration_score += 80
        else:
            risk_level = "high"
            risk_multiplier = min(risk_multiplier, 0.5)
            reasons.append("Candidate is moderately correlated with multiple open trades.")
            concentration_score += 30

    if sector_total > float(cfg["max_sector_exposure"]) and approved:
        risk_level = "high" if risk_level != "blocked" else risk_level
        risk_multiplier = min(risk_multiplier, 0.5)
        reasons.append("Same-sector exposure would exceed configured maximum.")
        concentration_score += 30

    if correlation_matrix is None and open_items and approved:
        risk_level = "medium"
        risk_multiplier = min(risk_multiplier, 0.75)
        concentration_score += 15

    if risk_level == "low" and concentration_score > 0:
        risk_level = "medium"
    if not reasons:
        reasons.append("No material concentration risks detected.")

    return _base_response(
        approved=approved,
        risk_level=risk_level,
        concentration_score=concentration_score,
        correlated_exposure={
            "candidate_ticker": candidate_ticker,
            "high_correlations": high_correlations,
            "moderate_correlations": moderate_correlations,
            "correlated_cluster_exposure": round(correlated_cluster_exposure, 6),
            "max_correlated_cluster_exposure": cfg["max_correlated_cluster_exposure"],
        },
        sector_exposure={
            "sector": candidate_sector,
            "existing_sector_risk": round(sector_risk_existing, 6),
            "candidate_risk": round(candidate_risk, 6),
            "sector_risk_if_added": round(sector_total, 6),
            "max_sector_exposure": cfg["max_sector_exposure"],
            "total_open_risk_if_added": round(total_if_added, 6),
            "max_total_open_risk_percent": cfg["max_total_open_risk_percent"],
        },
        ticker_overlap=ticker_overlap,
        risk_multiplier=risk_multiplier,
        reasons=reasons,
        warnings=warnings,
    )


def evaluate_portfolio_concentration(
    open_trades: list[dict],
    correlation_matrix: dict | None = None,
    config: dict | None = None,
) -> dict:
    cfg = _config(config)
    trades = [trade for trade in (open_trades or []) if isinstance(trade, dict)]
    sector_exposure: dict[str, float] = {}
    ticker_exposure: dict[str, float] = {}
    for trade in trades:
        sector = _sector(trade)
        ticker = _ticker(trade)
        risk = _risk_percent(trade, cfg)
        sector_exposure[sector] = round(sector_exposure.get(sector, 0.0) + risk, 6)
        ticker_exposure[ticker] = round(ticker_exposure.get(ticker, 0.0) + risk, 6)

    warnings: list[str] = []
    reasons: list[str] = []
    risk_level = "low"
    risk_multiplier = 1.0
    for sector, exposure in sector_exposure.items():
        if sector != "unknown" and exposure > float(cfg["max_sector_exposure"]):
            risk_level = "high"
            risk_multiplier = min(risk_multiplier, 0.5)
            reasons.append(f"Sector exposure is high: {sector}.")
    for ticker, exposure in ticker_exposure.items():
        if ticker and exposure > float(cfg["max_single_ticker_exposure"]):
            risk_level = "blocked"
            risk_multiplier = 0.0
            reasons.append(f"Single ticker exposure is above limit: {ticker}.")

    if correlation_matrix is None:
        warnings.append("Correlation matrix unavailable for portfolio-level concentration analysis.")
        if risk_level == "low":
            risk_level = "medium"
            risk_multiplier = min(risk_multiplier, 0.75)

    return _base_response(
        approved=risk_level != "blocked",
        risk_level=risk_level,
        concentration_score=100.0 if risk_level == "blocked" else 50.0 if risk_level == "high" else 15.0 if warnings else 0.0,
        correlated_exposure={"trade_count": len(trades), "matrix_available": correlation_matrix is not None},
        sector_exposure=sector_exposure,
        ticker_overlap=[],
        risk_multiplier=risk_multiplier,
        reasons=reasons or ["Portfolio concentration is within configured limits."],
        warnings=warnings,
    )
