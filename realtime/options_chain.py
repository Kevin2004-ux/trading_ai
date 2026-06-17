from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
import math

import requests

import config
from providers.options_data_provider import is_ibkr_options_data_provider


SOURCE_NAME = "polygon_options"
UNAVAILABLE_SOURCE = "unavailable"
POLYGON_BASE_URL = "https://api.polygon.io"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _response(
    ok: bool,
    ticker: str,
    data: Any = None,
    error: str | None = None,
    source: str = SOURCE_NAME,
) -> dict:
    return {
        "ok": ok,
        "ticker": str(ticker or "").upper(),
        "source": source,
        "timestamp": _now_iso(),
        "data": data,
        "error": error,
    }


def _safe_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(numeric):
        return None
    return numeric


def _safe_int(value: Any) -> int | None:
    numeric = _safe_float(value)
    if numeric is None:
        return None
    return int(numeric)


def _normalize_option_type(value: Any) -> str | None:
    normalized = str(value or "").strip().lower()
    if normalized in {"call", "put"}:
        return normalized
    if normalized in {"c", "calls"}:
        return "call"
    if normalized in {"p", "puts"}:
        return "put"
    return None


def _parse_expiration(value: Any) -> datetime | None:
    if value is None:
        return None
    try:
        expiration = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        try:
            expiration = datetime.strptime(str(value), "%Y-%m-%d")
        except ValueError:
            return None

    if expiration.tzinfo is None:
        expiration = expiration.replace(tzinfo=timezone.utc)
    else:
        expiration = expiration.astimezone(timezone.utc)
    return expiration


def _expiration_date_str(value: Any) -> str | None:
    expiration = _parse_expiration(value)
    if expiration is None:
        return None
    return expiration.date().isoformat()


def _days_to_expiration(expiration: Any) -> int | None:
    expiration_dt = _parse_expiration(expiration)
    if expiration_dt is None:
        return None
    current_date = datetime.now(timezone.utc).date()
    return (expiration_dt.date() - current_date).days


def _get_nested(container: dict, *keys: str) -> Any:
    current: Any = container
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _extract_chain_rows(raw_chain: list[dict] | dict) -> list[dict]:
    if isinstance(raw_chain, list):
        return [item for item in raw_chain if isinstance(item, dict)]
    if not isinstance(raw_chain, dict):
        return []

    for key in ("results", "contracts", "options", "chain", "data"):
        value = raw_chain.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
        if isinstance(value, dict):
            nested = _extract_chain_rows(value)
            if nested:
                return nested
    return []


def calculate_option_metrics(
    option: dict,
    underlying_price: float,
    expected_target_price: float | None = None,
) -> dict:
    bid = _safe_float(option.get("bid"))
    ask = _safe_float(option.get("ask"))
    mid = _safe_float(option.get("mid"))
    if mid is None and bid is not None and ask is not None:
        mid = round((bid + ask) / 2.0, 4)

    strike = _safe_float(option.get("strike"))
    option_type = _normalize_option_type(option.get("option_type"))
    spread_percent = None
    if bid is not None and ask is not None and mid not in (None, 0) and ask >= bid:
        spread_percent = (ask - bid) / mid

    breakeven_price = None
    breakeven_move_percent = None
    expected_value_at_target = None
    expected_profit_per_share = None
    expected_profit_per_contract = None
    target_reaches_breakeven = None

    if strike is not None and mid is not None and option_type in {"call", "put"}:
        if option_type == "call":
            breakeven_price = strike + mid
            if underlying_price and underlying_price > 0:
                breakeven_move_percent = (breakeven_price - underlying_price) / underlying_price
            if expected_target_price is not None:
                expected_value_at_target = max(expected_target_price - strike, 0.0)
                expected_profit_per_share = expected_value_at_target - mid
                target_reaches_breakeven = expected_target_price >= breakeven_price
        else:
            breakeven_price = strike - mid
            if underlying_price and underlying_price > 0:
                breakeven_move_percent = (underlying_price - breakeven_price) / underlying_price
            if expected_target_price is not None:
                expected_value_at_target = max(strike - expected_target_price, 0.0)
                expected_profit_per_share = expected_value_at_target - mid
                target_reaches_breakeven = expected_target_price <= breakeven_price

    if expected_profit_per_share is not None:
        expected_profit_per_contract = expected_profit_per_share * 100.0

    return {
        "mid": mid,
        "spread_percent": spread_percent,
        "breakeven_price": breakeven_price,
        "breakeven_move_percent": breakeven_move_percent,
        "expected_value_at_target": expected_value_at_target,
        "expected_profit_per_share": expected_profit_per_share,
        "expected_profit_per_contract": expected_profit_per_contract,
        "target_reaches_breakeven": target_reaches_breakeven,
    }


def normalize_options_chain(raw_chain: list[dict] | dict) -> list[dict]:
    rows = _extract_chain_rows(raw_chain)
    normalized: list[dict] = []

    for item in rows:
        details = item.get("details", {}) if isinstance(item.get("details"), dict) else {}
        quote = item.get("last_quote", {}) if isinstance(item.get("last_quote"), dict) else item.get("quote", {}) if isinstance(item.get("quote"), dict) else {}
        day = item.get("day", {}) if isinstance(item.get("day"), dict) else {}
        greeks = item.get("greeks", {}) if isinstance(item.get("greeks"), dict) else {}
        last_trade = item.get("last_trade", {}) if isinstance(item.get("last_trade"), dict) else {}

        option_contract = (
            item.get("option_contract")
            or details.get("ticker")
            or item.get("ticker")
            or item.get("symbol")
        )
        underlying_ticker = (
            item.get("underlying_ticker")
            or details.get("underlying_ticker")
            or item.get("underlying")
            or item.get("ticker_underlying")
        )
        option_type = _normalize_option_type(
            item.get("option_type")
            or details.get("contract_type")
            or item.get("contract_type")
            or item.get("type")
        )
        strike = _safe_float(
            item.get("strike")
            or details.get("strike_price")
            or item.get("strike_price")
        )
        expiration = (
            item.get("expiration")
            or details.get("expiration_date")
            or item.get("expiration_date")
        )
        days_to_expiration = _safe_int(item.get("days_to_expiration"))
        if days_to_expiration is None:
            days_to_expiration = _days_to_expiration(expiration)

        bid = _safe_float(item.get("bid"))
        if bid is None:
            bid = _safe_float(quote.get("bid") or quote.get("p"))
        ask = _safe_float(item.get("ask"))
        if ask is None:
            ask = _safe_float(quote.get("ask") or quote.get("P"))
        last = _safe_float(item.get("last"))
        if last is None:
            last = _safe_float(day.get("close"))
        if last is None:
            last = _safe_float(last_trade.get("price") or last_trade.get("p"))
        volume = _safe_float(item.get("volume"))
        if volume is None:
            volume = _safe_float(day.get("volume") or day.get("v"))
        open_interest = _safe_float(item.get("open_interest"))
        implied_volatility = _safe_float(item.get("implied_volatility") or item.get("iv"))
        iv_rank = _safe_float(item.get("iv_rank"))
        iv_percentile = _safe_float(item.get("iv_percentile"))

        normalized_option = {
            "ticker": str(option_contract or "").upper(),
            "underlying_ticker": str(underlying_ticker or "").upper(),
            "option_contract": str(option_contract or "").upper(),
            "option_type": option_type,
            "strike": strike,
            "expiration": _expiration_date_str(expiration),
            "days_to_expiration": days_to_expiration,
            "bid": bid,
            "ask": ask,
            "mid": _safe_float(item.get("mid")),
            "last": last,
            "volume": volume,
            "open_interest": open_interest,
            "implied_volatility": implied_volatility,
            "iv_rank": iv_rank,
            "iv_percentile": iv_percentile,
            "delta": _safe_float(item.get("delta") if item.get("delta") is not None else greeks.get("delta")),
            "gamma": _safe_float(item.get("gamma") if item.get("gamma") is not None else greeks.get("gamma")),
            "theta": _safe_float(item.get("theta") if item.get("theta") is not None else greeks.get("theta")),
            "vega": _safe_float(item.get("vega") if item.get("vega") is not None else greeks.get("vega")),
            "rho": _safe_float(item.get("rho") if item.get("rho") is not None else greeks.get("rho")),
            "spread_percent": _safe_float(item.get("spread_percent")),
            "breakeven_price": _safe_float(item.get("breakeven_price")),
            "breakeven_move_percent": _safe_float(item.get("breakeven_move_percent")),
        }

        metrics = calculate_option_metrics(
            normalized_option,
            underlying_price=_safe_float(item.get("underlying_price")) or 0.0,
            expected_target_price=_safe_float(item.get("expected_target_price")),
        )
        normalized_option.update(
            {
                "mid": metrics.get("mid"),
                "spread_percent": metrics.get("spread_percent"),
                "breakeven_price": metrics.get("breakeven_price"),
                "breakeven_move_percent": metrics.get("breakeven_move_percent"),
            }
        )

        normalized.append(normalized_option)

    return normalized


def get_options_chain(
    ticker: str,
    expiration: str | None = None,
    min_days_to_expiration: int = 14,
    max_days_to_expiration: int = 56,
) -> dict:
    if is_ibkr_options_data_provider():
        from providers.ibkr_provider import get_ibkr_options_chain

        return get_ibkr_options_chain(
            ticker,
            expiration=expiration,
            min_days_to_expiration=min_days_to_expiration,
            max_days_to_expiration=max_days_to_expiration,
        )

    api_key = getattr(config, "POLYGON_API_KEY", None)
    if not api_key:
        return _response(
            False,
            ticker,
            error="POLYGON_API_KEY is not configured for live options-chain data.",
            source=UNAVAILABLE_SOURCE,
        )

    try:
        next_url = f"{POLYGON_BASE_URL}/v3/snapshot/options/{str(ticker or '').upper()}"
        params: dict[str, Any] | None = {"limit": 250}
        rows: list[dict] = []

        while next_url:
            response = requests.get(
                next_url,
                params=params,
                headers={"Authorization": f"Bearer {api_key}"},
                timeout=20,
            )
            response.raise_for_status()
            payload = response.json()
            rows.extend(payload.get("results", []) if isinstance(payload, dict) else [])
            next_url = payload.get("next_url") if isinstance(payload, dict) else None
            params = None

        normalized = normalize_options_chain(rows)
        filtered = []
        for option in normalized:
            dte = _safe_int(option.get("days_to_expiration"))
            option_expiration = option.get("expiration")
            if expiration and option_expiration != expiration:
                continue
            if dte is None:
                continue
            if dte < min_days_to_expiration or dte > max_days_to_expiration:
                continue
            filtered.append(option)

        if not filtered:
            return _response(
                False,
                ticker,
                data={
                    "contracts": [],
                    "row_count": 0,
                    "expiration": expiration,
                    "filters": {
                        "min_days_to_expiration": min_days_to_expiration,
                        "max_days_to_expiration": max_days_to_expiration,
                    },
                },
                error="No option contracts matched the requested expiration window.",
            )

        return _response(
            True,
            ticker,
            data={
                "contracts": filtered,
                "row_count": len(filtered),
                "expiration": expiration,
                "filters": {
                    "min_days_to_expiration": min_days_to_expiration,
                    "max_days_to_expiration": max_days_to_expiration,
                },
            },
        )
    except requests.RequestException as exc:
        return _response(False, ticker, error=f"Failed to load options chain: {exc}")
    except Exception as exc:
        return _response(False, ticker, error=f"Unexpected error while loading options chain: {exc}")
