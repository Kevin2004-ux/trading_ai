from __future__ import annotations

import importlib
import math
import os
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterator

import pandas as pd

import config


SOURCE_NAME = "ibkr"
UNAVAILABLE_SOURCE = "unavailable"


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
        "ticker": str(ticker or "").strip().upper(),
        "source": source,
        "timestamp": _now_iso(),
        "data": data,
        "error": error,
    }


def _setting(name: str, default: Any = None) -> Any:
    return os.getenv(name) or getattr(config, name, default) or default


def _bool_setting(name: str, default: bool = False) -> bool:
    value = _setting(name, default)
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def get_ibkr_config() -> dict:
    return {
        "host": str(_setting("IBKR_HOST", "127.0.0.1")),
        "port": int(_setting("IBKR_PORT", 7496)),
        "client_id": int(_setting("IBKR_CLIENT_ID", 123)),
        "read_only": _bool_setting("IBKR_READ_ONLY", True),
        "use_delayed_data": _bool_setting("IBKR_USE_DELAYED_DATA", True),
    }


def _load_ib_insync():
    try:
        module = importlib.import_module("ib_insync")
    except Exception as exc:
        return None, f"ib_insync is not installed or could not be imported: {exc}"
    return module, None


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


def _to_iso_timestamp(value: Any) -> str | None:
    if value in (None, ""):
        return None
    try:
        ts = pd.Timestamp(value)
    except Exception:
        return None
    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    else:
        ts = ts.tz_convert("UTC")
    return ts.isoformat()


@contextmanager
def _ibkr_connection() -> Iterator[tuple[Any, Any, dict]]:
    ib_module, import_error = _load_ib_insync()
    if import_error:
        raise RuntimeError(import_error)

    cfg = get_ibkr_config()
    ib = ib_module.IB()
    try:
        ib.connect(
            cfg["host"],
            cfg["port"],
            clientId=cfg["client_id"],
            readonly=True,
            timeout=8,
        )
        if cfg["use_delayed_data"]:
            try:
                # 3 = delayed data, 4 = delayed frozen. Delayed avoids requiring live subscriptions.
                ib.reqMarketDataType(3)
            except Exception:
                pass
        yield ib, ib_module, cfg
    finally:
        try:
            if ib.isConnected():
                ib.disconnect()
        except Exception:
            pass


def check_ibkr_connection() -> dict:
    cfg = get_ibkr_config()
    ib_module, import_error = _load_ib_insync()
    if import_error:
        return {
            "ok": False,
            "source": UNAVAILABLE_SOURCE,
            "timestamp": _now_iso(),
            "connected": False,
            "read_only": cfg["read_only"],
            "use_delayed_data": cfg["use_delayed_data"],
            "host": cfg["host"],
            "port": cfg["port"],
            "client_id": cfg["client_id"],
            "error": import_error,
        }

    ib = ib_module.IB()
    try:
        ib.connect(cfg["host"], cfg["port"], clientId=cfg["client_id"], readonly=True, timeout=8)
        if cfg["use_delayed_data"]:
            ib.reqMarketDataType(3)
        connected = bool(ib.isConnected())
        return {
            "ok": connected,
            "source": SOURCE_NAME if connected else UNAVAILABLE_SOURCE,
            "timestamp": _now_iso(),
            "connected": connected,
            "read_only": True,
            "use_delayed_data": cfg["use_delayed_data"],
            "host": cfg["host"],
            "port": cfg["port"],
            "client_id": cfg["client_id"],
            "error": None if connected else "IBKR connection could not be established.",
        }
    except Exception as exc:
        return {
            "ok": False,
            "source": UNAVAILABLE_SOURCE,
            "timestamp": _now_iso(),
            "connected": False,
            "read_only": True,
            "use_delayed_data": cfg["use_delayed_data"],
            "host": cfg["host"],
            "port": cfg["port"],
            "client_id": cfg["client_id"],
            "error": f"IBKR connection failed: {exc}",
        }
    finally:
        try:
            if ib.isConnected():
                ib.disconnect()
        except Exception:
            pass


def _stock_contract(ib_module: Any, ticker: str):
    return ib_module.Stock(str(ticker or "").strip().upper(), "SMART", "USD")


def _normalize_ibkr_bar(bar: Any) -> dict:
    return {
        "timestamp": _to_iso_timestamp(getattr(bar, "date", None)),
        "open": _safe_float(getattr(bar, "open", None)),
        "high": _safe_float(getattr(bar, "high", None)),
        "low": _safe_float(getattr(bar, "low", None)),
        "close": _safe_float(getattr(bar, "close", None)),
        "volume": _safe_float(getattr(bar, "volume", None)),
    }


def _latest_bar_quote_fallback(historical_result: dict) -> dict | None:
    bars = (historical_result.get("data") or {}).get("bars", []) if isinstance(historical_result, dict) else []
    if not bars:
        return None
    latest_bar = bars[-1]
    latest_close = _safe_float(latest_bar.get("close")) if isinstance(latest_bar, dict) else None
    if latest_close is None:
        return None
    return {
        "last_price": latest_close,
        "previous_close": latest_close,
        "day_volume": _safe_float(latest_bar.get("volume")),
        "last_trade_timestamp": latest_bar.get("timestamp"),
        "quote_source": "historical_bar_fallback",
        "is_live_quote": False,
        "warning": "IBKR quote unavailable; using latest historical close.",
    }


def get_ibkr_historical_bars(ticker: str, lookback_days: int = 180) -> dict:
    normalized_ticker = str(ticker or "").strip().upper()
    try:
        with _ibkr_connection() as (ib, ib_module, cfg):
            contract = _stock_contract(ib_module, normalized_ticker)
            ib.qualifyContracts(contract)
            duration_days = max(int(lookback_days or 1), 1)
            bars = ib.reqHistoricalData(
                contract,
                endDateTime="",
                durationStr=f"{duration_days} D",
                barSizeSetting="1 day",
                whatToShow="TRADES",
                useRTH=True,
                formatDate=1,
                keepUpToDate=False,
            )
            rows = [_normalize_ibkr_bar(bar) for bar in bars or []]
            rows = [row for row in rows if all(row.get(column) is not None for column in ("timestamp", "open", "high", "low", "close", "volume"))]
            if not rows:
                return _response(
                    False,
                    normalized_ticker,
                    data={"bars": [], "row_count": 0, "use_delayed_data": cfg["use_delayed_data"]},
                    error="IBKR returned no historical OHLCV bars.",
                )
            return _response(
                True,
                normalized_ticker,
                data={
                    "bars": rows,
                    "row_count": len(rows),
                    "start_timestamp": rows[0]["timestamp"],
                    "end_timestamp": rows[-1]["timestamp"],
                    "schema": ["open", "high", "low", "close", "volume", "timestamp"],
                    "use_delayed_data": cfg["use_delayed_data"],
                },
            )
    except Exception as exc:
        return _response(False, normalized_ticker, error=f"IBKR historical bars unavailable: {exc}", source=UNAVAILABLE_SOURCE)


def _get_ibkr_quote_snapshot(ticker: str, market_data_type: int | None = None, label: str = "snapshot") -> dict:
    normalized_ticker = str(ticker or "").strip().upper()
    try:
        with _ibkr_connection() as (ib, ib_module, cfg):
            requested_market_data_type = market_data_type or (3 if cfg["use_delayed_data"] else 1)
            try:
                ib.reqMarketDataType(requested_market_data_type)
            except Exception:
                pass
            contract = _stock_contract(ib_module, normalized_ticker)
            ib.qualifyContracts(contract)
            ticker_data = ib.reqMktData(contract, "", True, False)
            ib.sleep(2)
            market_price = _safe_float(ticker_data.marketPrice() if hasattr(ticker_data, "marketPrice") else None)
            last_price = (
                market_price
                or _safe_float(getattr(ticker_data, "last", None))
                or _safe_float(getattr(ticker_data, "close", None))
                or _safe_float(getattr(ticker_data, "bid", None))
                or _safe_float(getattr(ticker_data, "ask", None))
            )
            previous_close = _safe_float(getattr(ticker_data, "close", None))
            day_volume = _safe_float(getattr(ticker_data, "volume", None))
            last_time = getattr(ticker_data, "time", None)
            try:
                ib.cancelMktData(contract)
            except Exception:
                pass

            if last_price is None and previous_close is None:
                return _response(
                    False,
                    normalized_ticker,
                    data={
                        "use_delayed_data": cfg["use_delayed_data"],
                        "requested_market_data_type": requested_market_data_type,
                        "market_data_label": label,
                        "market_data_type_returned": getattr(ticker_data, "marketDataType", None),
                    },
                    error="IBKR returned no usable quote. Market data subscription or delayed data permission may be unavailable. IBKR error 10089 commonly indicates missing market data permissions.",
                )

            return _response(
                True,
                normalized_ticker,
                data={
                    "last_price": last_price,
                    "previous_close": previous_close,
                    "day_volume": day_volume,
                    "last_trade_timestamp": _to_iso_timestamp(last_time),
                    "bid": _safe_float(getattr(ticker_data, "bid", None)),
                    "ask": _safe_float(getattr(ticker_data, "ask", None)),
                    "use_delayed_data": cfg["use_delayed_data"],
                    "requested_market_data_type": requested_market_data_type,
                    "market_data_label": label,
                    "market_data_type_returned": getattr(ticker_data, "marketDataType", None),
                    "quote_source": SOURCE_NAME,
                    "is_live_quote": requested_market_data_type == 1,
                },
            )
    except Exception as exc:
        return _response(False, normalized_ticker, error=f"IBKR quote unavailable: {exc}", source=UNAVAILABLE_SOURCE)


def get_ibkr_live_quote(ticker: str) -> dict:
    cfg = get_ibkr_config()
    return _get_ibkr_quote_snapshot(
        ticker,
        market_data_type=3 if cfg["use_delayed_data"] else 1,
        label="delayed_snapshot" if cfg["use_delayed_data"] else "live_snapshot",
    )


def get_ibkr_market_snapshot(ticker: str, lookback_days: int = 180) -> dict:
    from realtime.market_data import calculate_technical_snapshot, get_data_freshness, normalize_ohlcv

    historical_result = get_ibkr_historical_bars(ticker, lookback_days=lookback_days)
    if not historical_result["ok"]:
        return historical_result

    bars_df = normalize_ohlcv(historical_result["data"]["bars"])
    quote_result = get_ibkr_live_quote(ticker)
    quote_data = quote_result["data"] if quote_result["ok"] else None
    data_quality_warnings = []
    fallback_used = False
    if not quote_data:
        fallback_quote = _latest_bar_quote_fallback(historical_result)
        if fallback_quote:
            quote_data = fallback_quote
            fallback_used = True
            data_quality_warnings.append("IBKR quote unavailable; using latest historical close.")
    data = {
        "quote": quote_data,
        "quote_error": quote_result["error"],
        "quote_fallback_used": fallback_used,
        "bars": historical_result["data"]["bars"],
        "row_count": historical_result["data"]["row_count"],
        "technical_snapshot": calculate_technical_snapshot(bars_df),
        "data_freshness": get_data_freshness(bars_df),
        "use_delayed_data": historical_result["data"].get("use_delayed_data"),
        "data_quality_warnings": data_quality_warnings,
    }
    return _response(True, ticker, data=data)


def get_ibkr_options_chain(
    ticker: str,
    expiration: str | None = None,
    min_days_to_expiration: int = 14,
    max_days_to_expiration: int = 56,
) -> dict:
    normalized_ticker = str(ticker or "").strip().upper()
    try:
        with _ibkr_connection() as (ib, ib_module, cfg):
            underlying = _stock_contract(ib_module, normalized_ticker)
            qualified = ib.qualifyContracts(underlying)
            underlying_contract = qualified[0] if qualified else underlying
            params = ib.reqSecDefOptParams(
                underlying_contract.symbol,
                "",
                underlying_contract.secType,
                underlying_contract.conId,
            )
            expirations: list[str] = []
            strikes: list[float] = []
            exchanges: list[str] = []
            for item in params or []:
                expirations.extend(list(getattr(item, "expirations", []) or []))
                strikes.extend([float(strike) for strike in (getattr(item, "strikes", []) or []) if _safe_float(strike) is not None])
                exchanges.append(str(getattr(item, "exchange", "") or ""))

            expirations = sorted(set(expirations))
            filtered_expirations = []
            current_date = datetime.now(timezone.utc).date()
            for raw_expiration in expirations:
                parsed = pd.Timestamp(str(raw_expiration)).date()
                dte = (parsed - current_date).days
                if expiration and parsed.isoformat() != expiration:
                    continue
                if min_days_to_expiration <= dte <= max_days_to_expiration:
                    filtered_expirations.append(parsed.isoformat())

            data = {
                "contracts": [],
                "row_count": 0,
                "expiration": expiration,
                "filters": {
                    "min_days_to_expiration": min_days_to_expiration,
                    "max_days_to_expiration": max_days_to_expiration,
                },
                "metadata": {
                    "expiration_count": len(expirations),
                    "matching_expirations": filtered_expirations,
                    "strike_count": len(set(strikes)),
                    "exchanges": sorted({exchange for exchange in exchanges if exchange}),
                    "use_delayed_data": cfg["use_delayed_data"],
                },
            }
            return _response(
                False,
                normalized_ticker,
                data=data,
                error="IBKR option chain metadata is reachable, but full option quote chains are not enabled yet.",
            )
    except Exception as exc:
        return _response(
            False,
            normalized_ticker,
            data={
                "contracts": [],
                "row_count": 0,
                "expiration": expiration,
                "filters": {
                    "min_days_to_expiration": min_days_to_expiration,
                    "max_days_to_expiration": max_days_to_expiration,
                },
            },
            error=f"IBKR options chain unavailable: {exc}",
            source=UNAVAILABLE_SOURCE,
        )


def diagnose_ibkr_market_data_permissions(ticker: str = "AAPL") -> dict:
    normalized_ticker = str(ticker or "AAPL").strip().upper() or "AAPL"
    warnings: list[str] = []
    errors: list[str] = []

    connection = check_ibkr_connection()
    historical_bars = get_ibkr_historical_bars(normalized_ticker, lookback_days=30)
    quote_snapshot = _get_ibkr_quote_snapshot(normalized_ticker, market_data_type=1, label="live_snapshot")
    delayed_quote_snapshot = _get_ibkr_quote_snapshot(normalized_ticker, market_data_type=3, label="delayed_snapshot")
    delayed_frozen_quote_snapshot = _get_ibkr_quote_snapshot(normalized_ticker, market_data_type=4, label="delayed_frozen_snapshot")
    options_metadata = get_ibkr_options_chain(normalized_ticker)
    options_quotes = {
        "ok": False,
        "source": SOURCE_NAME,
        "timestamp": _now_iso(),
        "data": None,
        "error": "Full IBKR option quote-chain retrieval is not enabled yet.",
    }

    historical_available = bool(historical_bars.get("ok"))
    quote_available = bool(quote_snapshot.get("ok") or delayed_quote_snapshot.get("ok") or delayed_frozen_quote_snapshot.get("ok"))
    options_metadata_available = bool((options_metadata.get("data") or {}).get("metadata"))
    options_quotes_available = False

    likely_missing_subscriptions = []
    quote_errors = " ".join(
        str(item.get("error") or "")
        for item in (quote_snapshot, delayed_quote_snapshot, delayed_frozen_quote_snapshot)
    )
    if not quote_available:
        likely_missing_subscriptions.append("IBKR stock market data subscription or delayed market data permission for quote snapshots.")
        warnings.append("IBKR quote unavailable; historical daily bars may still be usable for after-close swing scans.")
    if "10089" in quote_errors or "subscription" in quote_errors.lower():
        warnings.append("IBKR error 10089 commonly indicates missing market data subscriptions or permissions.")
    if not options_quotes_available:
        likely_missing_subscriptions.append("IBKR options quote-chain market data subscription or provider implementation.")
        warnings.append("IBKR options metadata is separate from full option quote-chain availability.")

    return {
        "ok": bool(connection.get("ok")) and historical_available,
        "ticker": normalized_ticker,
        "timestamp": _now_iso(),
        "connection": connection,
        "historical_bars": historical_bars,
        "quote_snapshot": quote_snapshot,
        "delayed_quote_snapshot": delayed_quote_snapshot,
        "delayed_frozen_quote_snapshot": delayed_frozen_quote_snapshot,
        "options_metadata": options_metadata,
        "options_quotes": options_quotes,
        "permissions_summary": {
            "historical_bars_available": historical_available,
            "live_or_delayed_quotes_available": quote_available,
            "options_metadata_available": options_metadata_available,
            "options_quotes_available": options_quotes_available,
            "likely_missing_subscriptions": likely_missing_subscriptions,
        },
        "warnings": warnings,
        "errors": errors,
    }
