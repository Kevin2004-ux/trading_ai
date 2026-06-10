from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from math import floor
from typing import Any


DEFAULT_POSITION_SIZING_CONFIG = {
    "account_size": 10000.0,
    "risk_mode": "normal",
    "risk_per_trade_percent": 0.01,
    "max_option_premium_percent": 0.01,
}

RISK_MODE_DEFAULTS = {
    "conservative": {
        "risk_per_trade_percent": 0.005,
        "max_option_premium_percent": 0.005,
    },
    "normal": {
        "risk_per_trade_percent": 0.01,
        "max_option_premium_percent": 0.01,
    },
    "aggressive": {
        "risk_per_trade_percent": 0.015,
        "max_option_premium_percent": 0.015,
    },
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _normalize_ticker(value: Any) -> str:
    return str(value or "").strip().upper()


def _asset_type(trade: dict) -> str:
    preferred_instrument = str(trade.get("preferred_instrument", "")).strip().lower()
    asset_type = str(trade.get("asset_type", "")).strip().lower()
    if preferred_instrument == "option" or asset_type == "option" or trade.get("option_contract"):
        return "option"
    return "stock"


def get_position_sizing_config(
    account_size: float = 10000.0,
    risk_mode: str = "normal",
    config: dict | None = None,
) -> dict:
    normalized = dict(DEFAULT_POSITION_SIZING_CONFIG)
    warnings: list[str] = []
    if isinstance(config, dict):
        normalized.update(config)
    normalized["account_size"] = float(account_size)

    requested_risk_mode = str(risk_mode or normalized.get("risk_mode", "normal")).strip().lower()
    if requested_risk_mode not in RISK_MODE_DEFAULTS:
        warnings.append(f"Unknown risk_mode '{requested_risk_mode}' received; defaulted to normal.")
        requested_risk_mode = "normal"
    normalized["risk_mode"] = requested_risk_mode
    normalized.update(RISK_MODE_DEFAULTS[requested_risk_mode])
    normalized["warnings"] = warnings
    return normalized


def calculate_stock_position_size(
    trade: dict,
    account_size: float = 10000.0,
    risk_mode: str = "normal",
    config: dict | None = None,
) -> dict:
    sizing_config = get_position_sizing_config(account_size=account_size, risk_mode=risk_mode, config=config)
    warnings = list(sizing_config.get("warnings", []))
    ticker = _normalize_ticker(trade.get("ticker") or (trade.get("source_candidate", {}) or {}).get("ticker"))
    entry_price = _safe_float(trade.get("entry_price"))
    stop_loss = _safe_float(trade.get("stop_loss"))

    if entry_price is None or stop_loss is None or entry_price <= 0:
        return {
            "ok": False,
            "asset_type": "stock",
            "ticker": ticker,
            "account_size": sizing_config["account_size"],
            "risk_mode": sizing_config["risk_mode"],
            "risk_per_trade_percent": sizing_config["risk_per_trade_percent"],
            "max_risk_dollars": sizing_config["account_size"] * sizing_config["risk_per_trade_percent"],
            "entry_price": entry_price,
            "stop_loss": stop_loss,
            "risk_per_share": None,
            "shares": 0,
            "notional_exposure": 0.0,
            "estimated_max_loss": 0.0,
            "warnings": warnings,
            "error": "entry_price and stop_loss are required for stock position sizing.",
        }

    risk_per_share = abs(entry_price - stop_loss)
    max_risk_dollars = sizing_config["account_size"] * sizing_config["risk_per_trade_percent"]
    if risk_per_share <= 0:
        return {
            "ok": False,
            "asset_type": "stock",
            "ticker": ticker,
            "account_size": sizing_config["account_size"],
            "risk_mode": sizing_config["risk_mode"],
            "risk_per_trade_percent": sizing_config["risk_per_trade_percent"],
            "max_risk_dollars": max_risk_dollars,
            "entry_price": entry_price,
            "stop_loss": stop_loss,
            "risk_per_share": risk_per_share,
            "shares": 0,
            "notional_exposure": 0.0,
            "estimated_max_loss": 0.0,
            "warnings": warnings,
            "error": "risk_per_share must be greater than zero.",
        }

    shares = int(floor(max_risk_dollars / risk_per_share))
    notional_exposure = float(shares) * entry_price if shares > 0 else 0.0
    estimated_max_loss = float(shares) * risk_per_share if shares > 0 else 0.0
    if shares < 1:
        warnings.append("Suggested share size is zero because the stop distance is too large for the configured account and risk settings.")

    return {
        "ok": True,
        "asset_type": "stock",
        "ticker": ticker,
        "account_size": sizing_config["account_size"],
        "risk_mode": sizing_config["risk_mode"],
        "risk_per_trade_percent": sizing_config["risk_per_trade_percent"],
        "max_risk_dollars": max_risk_dollars,
        "entry_price": entry_price,
        "stop_loss": stop_loss,
        "risk_per_share": risk_per_share,
        "shares": max(shares, 0),
        "notional_exposure": notional_exposure,
        "estimated_max_loss": estimated_max_loss,
        "warnings": warnings,
        "error": None,
    }


def calculate_option_position_size(
    trade: dict,
    account_size: float = 10000.0,
    risk_mode: str = "normal",
    config: dict | None = None,
) -> dict:
    sizing_config = get_position_sizing_config(account_size=account_size, risk_mode=risk_mode, config=config)
    warnings = list(sizing_config.get("warnings", []))
    ticker = _normalize_ticker(
        trade.get("underlying_ticker")
        or trade.get("ticker")
        or (trade.get("source_candidate", {}) or {}).get("underlying_ticker")
    )
    option_contract = trade.get("option_contract") or trade.get("preferred_option_contract")
    premium = _safe_float(trade.get("entry_price"))
    if premium is None:
        premium = _safe_float(trade.get("mid"))
    if premium is None:
        premium = _safe_float(trade.get("premium"))

    if premium is None or premium <= 0:
        return {
            "ok": False,
            "asset_type": "option",
            "ticker": ticker,
            "option_contract": option_contract,
            "account_size": sizing_config["account_size"],
            "risk_mode": sizing_config["risk_mode"],
            "max_option_premium_percent": sizing_config["max_option_premium_percent"],
            "max_premium_dollars": sizing_config["account_size"] * sizing_config["max_option_premium_percent"],
            "premium": premium,
            "premium_per_contract": None,
            "contracts": 0,
            "notional_contract_exposure": 0.0,
            "estimated_max_loss": 0.0,
            "warnings": warnings,
            "error": "Option premium is required for option position sizing.",
        }

    premium_per_contract = premium * 100.0
    max_premium_dollars = sizing_config["account_size"] * sizing_config["max_option_premium_percent"]
    contracts = int(floor(max_premium_dollars / premium_per_contract))
    notional_contract_exposure = float(contracts) * premium_per_contract if contracts > 0 else 0.0
    estimated_max_loss = notional_contract_exposure
    if contracts < 1:
        warnings.append("Suggested contract size is zero because the option premium is too large for the configured account and risk settings.")

    return {
        "ok": True,
        "asset_type": "option",
        "ticker": ticker,
        "option_contract": option_contract,
        "account_size": sizing_config["account_size"],
        "risk_mode": sizing_config["risk_mode"],
        "max_option_premium_percent": sizing_config["max_option_premium_percent"],
        "max_premium_dollars": max_premium_dollars,
        "premium": premium,
        "premium_per_contract": premium_per_contract,
        "contracts": max(contracts, 0),
        "notional_contract_exposure": notional_contract_exposure,
        "estimated_max_loss": estimated_max_loss,
        "warnings": warnings,
        "error": None,
    }


def calculate_position_size(
    trade: dict,
    account_size: float = 10000.0,
    risk_mode: str = "normal",
    config: dict | None = None,
) -> dict:
    if not isinstance(trade, dict):
        sizing_config = get_position_sizing_config(account_size=account_size, risk_mode=risk_mode, config=config)
        return {
            "ok": False,
            "asset_type": "unknown",
            "ticker": "",
            "account_size": sizing_config["account_size"],
            "risk_mode": sizing_config["risk_mode"],
            "warnings": list(sizing_config.get("warnings", [])),
            "error": "Trade must be a dictionary.",
        }
    if _asset_type(trade) == "option":
        return calculate_option_position_size(trade, account_size=account_size, risk_mode=risk_mode, config=config)
    return calculate_stock_position_size(trade, account_size=account_size, risk_mode=risk_mode, config=config)


def apply_position_sizing_to_trades(
    trades: list[dict],
    account_size: float = 10000.0,
    risk_mode: str = "normal",
    config: dict | None = None,
) -> dict:
    sized_trades: list[dict] = []
    errors: list[str] = []
    for trade in trades or []:
        if not isinstance(trade, dict):
            continue
        sized_trade = deepcopy(trade)
        position_sizing = calculate_position_size(
            sized_trade,
            account_size=account_size,
            risk_mode=risk_mode,
            config=config,
        )
        sized_trade["position_sizing"] = position_sizing
        sized_trades.append(sized_trade)
        if position_sizing.get("error"):
            errors.append(str(position_sizing["error"]))

    return {
        "ok": True,
        "timestamp": _now_iso(),
        "account_size": float(account_size),
        "risk_mode": get_position_sizing_config(account_size=account_size, risk_mode=risk_mode, config=config)["risk_mode"],
        "trades": sized_trades,
        "errors": errors,
    }
