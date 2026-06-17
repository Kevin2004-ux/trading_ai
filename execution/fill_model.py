from __future__ import annotations

from copy import deepcopy
from typing import Any

from execution.slippage_model import estimate_option_slippage, estimate_stock_slippage


def _safe_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _asset_type(trade: dict) -> str:
    asset_type = str(trade.get("asset_type", "")).lower()
    preferred = str(trade.get("preferred_instrument", "")).lower()
    if asset_type == "option" or preferred == "option" or trade.get("option_contract"):
        return "option"
    return "stock"


def _direction_multiplier(trade: dict) -> float:
    return -1.0 if str(trade.get("direction", "long")).lower() == "short" else 1.0


def estimate_paper_fill(
    trade: dict,
    market_snapshot: dict | None = None,
    option_quote: dict | None = None,
    position_sizing: dict | None = None,
    config: dict | None = None,
) -> dict:
    if not isinstance(trade, dict):
        return {
            "ok": False,
            "ticker": "",
            "asset_type": "unknown",
            "intended_entry_price": None,
            "estimated_fill_price": None,
            "slippage": None,
            "fill_quality": "unavailable",
            "paper_fill_warning": "Trade must be a dictionary.",
            "error": "Trade must be a dictionary.",
        }

    working_trade = deepcopy(trade)
    if isinstance(position_sizing, dict):
        working_trade["position_sizing"] = position_sizing
    asset_type = _asset_type(working_trade)
    intended_entry = _safe_float(working_trade.get("entry_price"))
    ticker = str(working_trade.get("ticker") or working_trade.get("underlying_ticker") or "").upper()

    if intended_entry is None or intended_entry <= 0:
        return {
            "ok": False,
            "ticker": ticker,
            "asset_type": asset_type,
            "intended_entry_price": intended_entry,
            "estimated_fill_price": None,
            "slippage": None,
            "fill_quality": "unavailable",
            "paper_fill_warning": "Entry price is required for simulated fill modeling.",
            "error": "Entry price is required for simulated fill modeling.",
        }

    if asset_type == "option":
        slippage = estimate_option_slippage(working_trade, option_quote=option_quote, config=config)
        fill_price = _safe_float(slippage.get("estimated_fill_price"))
        warning = "; ".join(slippage.get("warnings", [])) if slippage.get("warnings") else "Paper option fill is simulated from bid/ask spread."
        return {
            "ok": bool(slippage.get("ok")) and fill_price is not None,
            "ticker": ticker,
            "asset_type": "option",
            "option_contract": working_trade.get("option_contract") or (option_quote or {}).get("option_contract"),
            "intended_entry_price": intended_entry,
            "estimated_fill_price": fill_price,
            "slippage": slippage,
            "fill_quality": slippage.get("fill_quality", "unavailable"),
            "paper_fill_warning": warning,
            "error": None if slippage.get("ok") else slippage.get("error"),
        }

    slippage = estimate_stock_slippage(working_trade, market_snapshot=market_snapshot, config=config)
    slippage_dollars = _safe_float(slippage.get("estimated_slippage_dollars"))
    fill_price = None
    if slippage_dollars is not None:
        fill_price = round(intended_entry + (_direction_multiplier(working_trade) * slippage_dollars), 4)
    fill_quality = "good"
    slippage_percent = _safe_float(slippage.get("estimated_slippage_percent"))
    if slippage_percent is None:
        fill_quality = "unavailable"
    elif slippage_percent > 0.4:
        fill_quality = "poor"
    elif slippage_percent > 0.15:
        fill_quality = "usable"

    warning = "Paper stock fill includes deterministic slippage and spread/impact assumptions."
    if slippage.get("warnings"):
        warning = "; ".join(slippage["warnings"])

    return {
        "ok": bool(slippage.get("ok")) and fill_price is not None,
        "ticker": ticker,
        "asset_type": "stock",
        "intended_entry_price": intended_entry,
        "estimated_fill_price": fill_price,
        "slippage": slippage,
        "fill_quality": fill_quality,
        "paper_fill_warning": warning,
        "error": None if slippage.get("ok") else slippage.get("error"),
    }


def apply_fill_model_to_trades(
    trades: list[dict],
    market_context: dict | None = None,
    config: dict | None = None,
) -> dict:
    filled_trades: list[dict] = []
    errors: list[str] = []
    context = market_context if isinstance(market_context, dict) else {}
    snapshots = context.get("market_snapshots", {}) if isinstance(context.get("market_snapshots"), dict) else {}
    option_quotes = context.get("option_quotes", {}) if isinstance(context.get("option_quotes"), dict) else {}

    for trade in trades or []:
        if not isinstance(trade, dict):
            continue
        ticker = str(trade.get("ticker") or trade.get("underlying_ticker") or "").upper()
        option_contract = trade.get("option_contract")
        fill = estimate_paper_fill(
            trade,
            market_snapshot=snapshots.get(ticker),
            option_quote=option_quotes.get(option_contract) if option_contract else None,
            position_sizing=trade.get("position_sizing") if isinstance(trade.get("position_sizing"), dict) else None,
            config=config,
        )
        filled = deepcopy(trade)
        filled["paper_fill"] = fill
        if fill.get("ok") and fill.get("estimated_fill_price") is not None:
            filled["intended_entry_price"] = fill["intended_entry_price"]
            filled["entry_price"] = fill["estimated_fill_price"]
        else:
            errors.append(fill.get("error") or f"Failed to estimate paper fill for {ticker}.")
        filled_trades.append(filled)

    return {
        "ok": not errors,
        "trades": filled_trades,
        "errors": errors,
    }

