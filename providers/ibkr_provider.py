from __future__ import annotations

import importlib
import math
import os
import signal
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterator

import pandas as pd

import config
from providers.ticker_normalizer import normalize_ticker_for_provider
from quality.data_quality import validate_market_data_quality


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


def _error_response(
    ticker: str,
    error: str,
    source: str = UNAVAILABLE_SOURCE,
    error_type: str | None = None,
    data: Any = None,
) -> dict:
    response = _response(False, ticker, data=data, error=error, source=source)
    if error_type:
        response["error_type"] = error_type
        response["provider"] = SOURCE_NAME
    return response


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
        "timeout_seconds": int(_setting("IBKR_TIMEOUT_SECONDS", 10)),
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


def _safe_int(value: Any) -> int | None:
    numeric = _safe_float(value)
    if numeric is None:
        return None
    return int(numeric)


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


class _IbkrTimeoutError(TimeoutError):
    pass


@contextmanager
def _ticker_timeout(seconds: int | float | None, ticker: str, operation: str):
    if not seconds or seconds <= 0:
        yield
        return
    if not hasattr(signal, "SIGALRM"):
        yield
        return
    if threading.current_thread() is not threading.main_thread():
        yield
        return

    previous_handler = signal.getsignal(signal.SIGALRM)

    def _handler(signum, frame):
        del signum, frame
        raise _IbkrTimeoutError(f"IBKR {operation} timed out for {ticker} after {seconds} seconds.")

    try:
        signal.signal(signal.SIGALRM, _handler)
        signal.setitimer(signal.ITIMER_REAL, float(seconds))
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous_handler)


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
        try:
            ib.RequestTimeout = cfg["timeout_seconds"]
        except Exception:
            pass
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


def _normalize_for_ibkr(ticker: str) -> dict:
    return normalize_ticker_for_provider(ticker, "ibkr")


def _option_contract(ib_module: Any, ticker: str, expiration: str, strike: float, right: str):
    return ib_module.Option(
        str(ticker or "").strip().upper(),
        expiration.replace("-", ""),
        float(strike),
        right.upper(),
        "SMART",
        currency="USD",
    )


def _normalize_ibkr_bar(bar: Any) -> dict:
    return {
        "timestamp": _to_iso_timestamp(getattr(bar, "date", None)),
        "open": _safe_float(getattr(bar, "open", None)),
        "high": _safe_float(getattr(bar, "high", None)),
        "low": _safe_float(getattr(bar, "low", None)),
        "close": _safe_float(getattr(bar, "close", None)),
        "volume": _safe_float(getattr(bar, "volume", None)),
    }


def _parse_ibkr_expiration(raw_expiration: Any) -> pd.Timestamp | None:
    if raw_expiration in (None, ""):
        return None
    value = str(raw_expiration)
    try:
        if len(value) == 8 and value.isdigit():
            return pd.Timestamp(datetime.strptime(value, "%Y%m%d").date(), tz="UTC")
        return pd.Timestamp(value, tz="UTC")
    except Exception:
        return None


def _get_greek_value(greeks: Any, name: str) -> float | None:
    return _safe_float(getattr(greeks, name, None)) if greeks is not None else None


def _option_contract_symbol(ticker: str, expiration: str, option_type: str, strike: float) -> str:
    strike_code = int(round(float(strike) * 1000))
    return f"{ticker.upper()}{expiration.replace('-', '')}{option_type.upper()[0]}{strike_code:08d}"


def _normalize_option_ticker_data(
    ticker_symbol: str,
    option_contract: Any,
    ticker_data: Any,
    underlying_price: float | None,
) -> dict:
    bid = _safe_float(getattr(ticker_data, "bid", None))
    ask = _safe_float(getattr(ticker_data, "ask", None))
    last = _safe_float(getattr(ticker_data, "last", None))
    close = _safe_float(getattr(ticker_data, "close", None))
    volume = _safe_float(getattr(ticker_data, "volume", None))
    open_interest = (
        _safe_float(getattr(ticker_data, "callOpenInterest", None))
        if str(getattr(option_contract, "right", "")).upper() == "C"
        else _safe_float(getattr(ticker_data, "putOpenInterest", None))
    )
    if open_interest is None:
        open_interest = _safe_float(getattr(ticker_data, "openInterest", None))
    mid = round((bid + ask) / 2.0, 4) if bid is not None and ask is not None and ask >= bid else None
    model_greeks = getattr(ticker_data, "modelGreeks", None)
    bid_greeks = getattr(ticker_data, "bidGreeks", None)
    ask_greeks = getattr(ticker_data, "askGreeks", None)
    expiration = str(getattr(option_contract, "lastTradeDateOrContractMonth", "") or "")
    expiration_iso = None
    parsed_expiration = _parse_ibkr_expiration(expiration)
    if parsed_expiration is not None:
        expiration_iso = parsed_expiration.date().isoformat()
    option_type = "call" if str(getattr(option_contract, "right", "")).upper() == "C" else "put"
    strike = _safe_float(getattr(option_contract, "strike", None))

    return {
        "ticker": ticker_symbol,
        "underlying_ticker": str(getattr(option_contract, "symbol", "") or "").upper(),
        "option_contract": ticker_symbol,
        "option_type": option_type,
        "strike": strike,
        "expiration": expiration_iso,
        "days_to_expiration": (parsed_expiration.date() - datetime.now(timezone.utc).date()).days if parsed_expiration is not None else None,
        "bid": bid,
        "ask": ask,
        "mid": mid,
        "last": last,
        "close": close,
        "volume": volume,
        "open_interest": open_interest,
        "implied_volatility": _get_greek_value(model_greeks, "impliedVol"),
        "delta": _get_greek_value(model_greeks, "delta"),
        "gamma": _get_greek_value(model_greeks, "gamma"),
        "theta": _get_greek_value(model_greeks, "theta"),
        "vega": _get_greek_value(model_greeks, "vega"),
        "model_greeks": {
            "implied_volatility": _get_greek_value(model_greeks, "impliedVol"),
            "delta": _get_greek_value(model_greeks, "delta"),
            "gamma": _get_greek_value(model_greeks, "gamma"),
            "theta": _get_greek_value(model_greeks, "theta"),
            "vega": _get_greek_value(model_greeks, "vega"),
        } if model_greeks is not None else None,
        "bid_greeks": {
            "implied_volatility": _get_greek_value(bid_greeks, "impliedVol"),
            "delta": _get_greek_value(bid_greeks, "delta"),
            "gamma": _get_greek_value(bid_greeks, "gamma"),
            "theta": _get_greek_value(bid_greeks, "theta"),
            "vega": _get_greek_value(bid_greeks, "vega"),
        } if bid_greeks is not None else None,
        "ask_greeks": {
            "implied_volatility": _get_greek_value(ask_greeks, "impliedVol"),
            "delta": _get_greek_value(ask_greeks, "delta"),
            "gamma": _get_greek_value(ask_greeks, "gamma"),
            "theta": _get_greek_value(ask_greeks, "theta"),
            "vega": _get_greek_value(ask_greeks, "vega"),
        } if ask_greeks is not None else None,
        "underlying_price": underlying_price,
        "market_data_type_returned": getattr(ticker_data, "marketDataType", None),
    }


def _extract_option_metadata(params: Any, expiration: str | None, min_days_to_expiration: int, max_days_to_expiration: int, exchange_preference: str = "SMART") -> dict:
    expirations: list[str] = []
    strikes: list[float] = []
    exchanges: list[str] = []
    selected_exchange = exchange_preference
    for item in params or []:
        item_exchange = str(getattr(item, "exchange", "") or "")
        expirations.extend(list(getattr(item, "expirations", []) or []))
        strikes.extend([float(strike) for strike in (getattr(item, "strikes", []) or []) if _safe_float(strike) is not None])
        if item_exchange:
            exchanges.append(item_exchange)

    unique_expirations = []
    current_date = datetime.now(timezone.utc).date()
    for raw_expiration in sorted(set(expirations)):
        parsed = _parse_ibkr_expiration(raw_expiration)
        if parsed is None:
            continue
        dte = (parsed.date() - current_date).days
        if expiration and parsed.date().isoformat() != expiration:
            continue
        if min_days_to_expiration <= dte <= max_days_to_expiration:
            unique_expirations.append(parsed.date().isoformat())

    unique_strikes = sorted(set(strikes))
    exchange_set = sorted({exchange for exchange in exchanges if exchange})
    if selected_exchange not in exchange_set and exchange_set:
        selected_exchange = exchange_set[0]

    return {
        "expiration_count": len(set(expirations)),
        "matching_expirations": unique_expirations,
        "strike_count": len(unique_strikes),
        "strikes": unique_strikes,
        "exchanges": exchange_set,
        "selected_exchange": selected_exchange,
    }


def _select_near_money_option_specs(
    ticker: str,
    metadata: dict,
    underlying_price: float | None,
    max_contracts: int = 5,
) -> list[dict]:
    expirations = metadata.get("matching_expirations") or []
    strikes = metadata.get("strikes") or []
    if not expirations or not strikes or underlying_price is None:
        return []

    expiration = expirations[0]
    ranked_strikes = sorted(strikes, key=lambda strike: abs(float(strike) - underlying_price))
    contract_specs: list[dict] = []
    max_contracts = max(int(max_contracts or 1), 1)
    for strike in ranked_strikes:
        for right, option_type in (("C", "call"), ("P", "put")):
            contract_specs.append(
                {
                    "ticker": ticker.upper(),
                    "expiration": expiration,
                    "strike": float(strike),
                    "right": right,
                    "option_type": option_type,
                    "option_contract": _option_contract_symbol(ticker, expiration, option_type, float(strike)),
                }
            )
            if len(contract_specs) >= max_contracts:
                return contract_specs
    return contract_specs


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
        "warning": "IBKR live quote unavailable; using latest historical close.",
    }


def get_ibkr_historical_bars(ticker: str, lookback_days: int = 180) -> dict:
    original_ticker = str(ticker or "").strip().upper()
    normalized_result = _normalize_for_ibkr(original_ticker)
    if not normalized_result.get("ok"):
        return _error_response(original_ticker, normalized_result.get("error", "Ticker normalization failed."), error_type="symbol")
    ibkr_ticker = normalized_result["normalized_ticker"]
    try:
        with _ibkr_connection() as (ib, ib_module, cfg):
            contract = _stock_contract(ib_module, ibkr_ticker)
            with _ticker_timeout(cfg["timeout_seconds"], original_ticker, "historical bars"):
                qualified = ib.qualifyContracts(contract)
                if not qualified:
                    return _error_response(original_ticker, f"IBKR could not qualify stock contract for {original_ticker} using symbol {ibkr_ticker}.", error_type="symbol")
                duration_days = max(int(lookback_days or 1), 1)
                bars = ib.reqHistoricalData(
                    qualified[0],
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
                    original_ticker,
                    data={"bars": [], "row_count": 0, "use_delayed_data": cfg["use_delayed_data"]},
                    error="IBKR returned no historical OHLCV bars.",
                )
            return _response(
                True,
                original_ticker,
                data={
                    "bars": rows,
                    "row_count": len(rows),
                    "start_timestamp": rows[0]["timestamp"],
                    "end_timestamp": rows[-1]["timestamp"],
                    "schema": ["open", "high", "low", "close", "volume", "timestamp"],
                    "use_delayed_data": cfg["use_delayed_data"],
                    "provider_ticker": ibkr_ticker,
                    "ticker_normalization": normalized_result,
                },
            )
    except _IbkrTimeoutError as exc:
        return _error_response(original_ticker, str(exc), error_type="timeout")
    except Exception as exc:
        return _error_response(original_ticker, f"IBKR historical bars unavailable: {exc}")


def _get_ibkr_quote_snapshot(ticker: str, market_data_type: int | None = None, label: str = "snapshot") -> dict:
    original_ticker = str(ticker or "").strip().upper()
    normalized_result = _normalize_for_ibkr(original_ticker)
    if not normalized_result.get("ok"):
        return _error_response(original_ticker, normalized_result.get("error", "Ticker normalization failed."), error_type="symbol")
    ibkr_ticker = normalized_result["normalized_ticker"]
    try:
        with _ibkr_connection() as (ib, ib_module, cfg):
            requested_market_data_type = market_data_type or (3 if cfg["use_delayed_data"] else 1)
            try:
                ib.reqMarketDataType(requested_market_data_type)
            except Exception:
                pass
            contract = _stock_contract(ib_module, ibkr_ticker)
            with _ticker_timeout(cfg["timeout_seconds"], original_ticker, "quote snapshot"):
                qualified = ib.qualifyContracts(contract)
                if not qualified:
                    return _error_response(original_ticker, f"IBKR could not qualify stock contract for {original_ticker} using symbol {ibkr_ticker}.", error_type="symbol")
                contract = qualified[0]
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
                    original_ticker,
                    data={
                        "use_delayed_data": cfg["use_delayed_data"],
                        "requested_market_data_type": requested_market_data_type,
                        "market_data_label": label,
                        "market_data_type_returned": getattr(ticker_data, "marketDataType", None),
                        "provider_ticker": ibkr_ticker,
                        "ticker_normalization": normalized_result,
                    },
                    error="IBKR returned no usable quote. Market data subscription or delayed data permission may be unavailable. IBKR error 10089 commonly indicates missing market data permissions.",
                )

            return _response(
                True,
                original_ticker,
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
                    "provider_ticker": ibkr_ticker,
                    "ticker_normalization": normalized_result,
                },
            )
    except _IbkrTimeoutError as exc:
        return _error_response(original_ticker, str(exc), error_type="timeout")
    except Exception as exc:
        return _error_response(original_ticker, f"IBKR quote unavailable: {exc}")


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
            data_quality_warnings.append("IBKR live quote unavailable; using latest historical close.")
            data_quality_warnings.append("Not suitable for intraday entry decisions.")
    data = {
        "quote": quote_data,
        "quote_error": quote_result["error"],
        "quote_status": "available" if quote_result.get("ok") else "unavailable",
        "quote_fallback_used": fallback_used,
        "bars": historical_result["data"]["bars"],
        "row_count": historical_result["data"]["row_count"],
        "technical_snapshot": calculate_technical_snapshot(bars_df),
        "data_freshness": get_data_freshness(bars_df),
        "use_delayed_data": historical_result["data"].get("use_delayed_data"),
        "data_quality_warnings": data_quality_warnings,
    }
    response = _response(True, ticker, data=data)
    response["data"]["data_quality"] = validate_market_data_quality(response)
    return response


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
            metadata = _extract_option_metadata(params, expiration, min_days_to_expiration, max_days_to_expiration)
            data = {
                "contracts": [],
                "row_count": 0,
                "expiration": expiration,
                "filters": {
                    "min_days_to_expiration": min_days_to_expiration,
                    "max_days_to_expiration": max_days_to_expiration,
                },
                "metadata": {
                    "expiration_count": metadata["expiration_count"],
                    "matching_expirations": metadata["matching_expirations"],
                    "strike_count": metadata["strike_count"],
                    "exchanges": metadata["exchanges"],
                    "use_delayed_data": cfg["use_delayed_data"],
                    "selected_exchange": metadata["selected_exchange"],
                },
            }

            quote_diagnostic = _diagnose_ibkr_option_quotes_connected(
                ib,
                ib_module,
                cfg,
                normalized_ticker,
                underlying_contract,
                metadata,
                max_contracts=8,
            )
            quoted_contracts = quote_diagnostic.get("quotes") or []
            usable_contracts = [
                quote
                for quote in quoted_contracts
                if quote.get("ok") and (quote.get("bid") is not None or quote.get("ask") is not None or quote.get("last") is not None or quote.get("close") is not None)
            ]
            if usable_contracts:
                data["contracts"] = usable_contracts
                data["row_count"] = len(usable_contracts)
                data["diagnostic"] = quote_diagnostic
                return _response(True, normalized_ticker, data=data)

            data["diagnostic"] = quote_diagnostic
            return _response(
                False,
                normalized_ticker,
                data=data,
                error="IBKR option chain metadata is reachable, but option quote snapshots are unavailable. OPRA/options market data permissions may be missing.",
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


def _diagnose_ibkr_option_quotes_connected(
    ib: Any,
    ib_module: Any,
    cfg: dict,
    ticker: str,
    underlying_contract: Any,
    metadata: dict,
    max_contracts: int,
) -> dict:
    warnings: list[str] = []
    errors: list[str] = []
    contracts_tested: list[dict] = []
    quotes: list[dict] = []

    try:
        if cfg.get("use_delayed_data"):
            ib.reqMarketDataType(3)
    except Exception:
        pass

    underlying_quote = ib.reqMktData(underlying_contract, "", True, False)
    ib.sleep(2)
    underlying_price = (
        _safe_float(underlying_quote.marketPrice() if hasattr(underlying_quote, "marketPrice") else None)
        or _safe_float(getattr(underlying_quote, "last", None))
        or _safe_float(getattr(underlying_quote, "close", None))
        or _safe_float(getattr(underlying_quote, "bid", None))
        or _safe_float(getattr(underlying_quote, "ask", None))
    )
    try:
        ib.cancelMktData(underlying_contract)
    except Exception:
        pass

    specs = _select_near_money_option_specs(ticker, metadata, underlying_price, max_contracts=max_contracts)
    if not specs:
        warnings.append("No near-the-money option contracts could be selected from IBKR metadata.")

    for spec in specs:
        contract = _option_contract(ib_module, ticker, spec["expiration"], spec["strike"], spec["right"])
        try:
            qualified = ib.qualifyContracts(contract)
            if not qualified or getattr(qualified[0], "conId", None) in (None, 0):
                contracts_tested.append(spec)
                quotes.append(
                    {
                        "ok": False,
                        "option_contract": spec["option_contract"],
                        "underlying_ticker": ticker,
                        "option_type": spec["option_type"],
                        "strike": spec["strike"],
                        "expiration": spec["expiration"],
                        "bid": None,
                        "ask": None,
                        "mid": None,
                        "last": None,
                        "close": None,
                        "volume": None,
                        "open_interest": None,
                        "model_greeks": None,
                        "error": "IBKR could not qualify this option contract security definition.",
                    }
                )
                continue
            contract = qualified[0] if qualified else contract
            contracts_tested.append(spec)
            # IBKR rejects snapshot option requests with generic ticks attached.
            # Keep this diagnostic to quote fields only; open interest/Greeks may be None.
            ticker_data = ib.reqMktData(contract, "", True, False)
            ib.sleep(2)
            try:
                ib.cancelMktData(contract)
            except Exception:
                pass
            quote = _normalize_option_ticker_data(spec["option_contract"], contract, ticker_data, underlying_price)
            quote["ok"] = bool(quote.get("bid") is not None or quote.get("ask") is not None or quote.get("last") is not None or quote.get("close") is not None)
            quote["error"] = None if quote["ok"] else "IBKR returned no usable option quote fields."
            quotes.append(quote)
        except Exception as exc:
            message = str(exc)
            errors.append(message)
            quotes.append(
                {
                    "ok": False,
                    "option_contract": spec["option_contract"],
                    "underlying_ticker": ticker,
                    "option_type": spec["option_type"],
                    "strike": spec["strike"],
                    "expiration": spec["expiration"],
                    "bid": None,
                    "ask": None,
                    "mid": None,
                    "last": None,
                    "close": None,
                    "volume": None,
                    "open_interest": None,
                    "model_greeks": None,
                    "error": message,
                }
            )

    quote_errors = " ".join(str(quote.get("error") or "") for quote in quotes)
    option_quotes_available = any(quote.get("ok") for quote in quotes)
    likely_missing_opra = bool(quotes) and not option_quotes_available
    if "10089" in quote_errors or "subscription" in quote_errors.lower() or "permission" in quote_errors.lower():
        likely_missing_opra = True
        warnings.append("IBKR option quote snapshots appear blocked by OPRA/options market data permissions.")
    elif bool(quotes) and not option_quotes_available:
        warnings.append("IBKR option contracts qualified, but no usable bid/ask/last/close fields were returned.")

    return {
        "underlying_price": underlying_price,
        "contracts_tested": contracts_tested,
        "quotes": quotes,
        "permissions_summary": {
            "option_metadata_available": bool(metadata.get("matching_expirations") and metadata.get("strikes")),
            "option_quotes_available": option_quotes_available,
            "likely_missing_opra": likely_missing_opra,
            "errors": errors + [quote.get("error") for quote in quotes if quote.get("error")],
        },
        "warnings": warnings,
        "errors": errors,
    }


def diagnose_ibkr_option_quotes(ticker: str = "AAPL", max_contracts: int = 5) -> dict:
    normalized_ticker = str(ticker or "AAPL").strip().upper() or "AAPL"
    warnings: list[str] = []
    errors: list[str] = []
    underlying_quote: dict = {}
    metadata_result: dict = {}
    contracts_tested: list[dict] = []
    quotes: list[dict] = []
    permissions_summary = {
        "option_metadata_available": False,
        "option_quotes_available": False,
        "likely_missing_opra": False,
        "errors": [],
    }

    try:
        with _ibkr_connection() as (ib, ib_module, cfg):
            underlying = _stock_contract(ib_module, normalized_ticker)
            qualified = ib.qualifyContracts(underlying)
            underlying_contract = qualified[0] if qualified else underlying
            try:
                ib.reqMarketDataType(3 if cfg["use_delayed_data"] else 1)
            except Exception:
                pass

            underlying_ticker = ib.reqMktData(underlying_contract, "", True, False)
            ib.sleep(2)
            underlying_price = (
                _safe_float(underlying_ticker.marketPrice() if hasattr(underlying_ticker, "marketPrice") else None)
                or _safe_float(getattr(underlying_ticker, "last", None))
                or _safe_float(getattr(underlying_ticker, "close", None))
                or _safe_float(getattr(underlying_ticker, "bid", None))
                or _safe_float(getattr(underlying_ticker, "ask", None))
            )
            underlying_quote = {
                "ok": underlying_price is not None,
                "last_price": underlying_price,
                "previous_close": _safe_float(getattr(underlying_ticker, "close", None)),
                "bid": _safe_float(getattr(underlying_ticker, "bid", None)),
                "ask": _safe_float(getattr(underlying_ticker, "ask", None)),
                "market_data_type_returned": getattr(underlying_ticker, "marketDataType", None),
                "error": None if underlying_price is not None else "IBKR returned no usable underlying stock quote.",
            }
            try:
                ib.cancelMktData(underlying_contract)
            except Exception:
                pass

            params = ib.reqSecDefOptParams(
                underlying_contract.symbol,
                "",
                underlying_contract.secType,
                underlying_contract.conId,
            )
            metadata = _extract_option_metadata(params, None, 14, 56)
            metadata_result = {
                "ok": bool(metadata.get("matching_expirations") and metadata.get("strikes")),
                "expiration_count": metadata["expiration_count"],
                "matching_expirations": metadata["matching_expirations"],
                "strike_count": metadata["strike_count"],
                "exchanges": metadata["exchanges"],
                "selected_exchange": metadata["selected_exchange"],
                "use_delayed_data": cfg["use_delayed_data"],
            }
            diagnostic = _diagnose_ibkr_option_quotes_connected(
                ib,
                ib_module,
                cfg,
                normalized_ticker,
                underlying_contract,
                metadata,
                max_contracts=max_contracts,
            )
            contracts_tested = diagnostic["contracts_tested"]
            quotes = diagnostic["quotes"]
            warnings.extend(diagnostic["warnings"])
            errors.extend(diagnostic["errors"])
            permissions_summary = diagnostic["permissions_summary"]
    except Exception as exc:
        errors.append(str(exc))
        permissions_summary["errors"].append(str(exc))

    if permissions_summary.get("likely_missing_opra"):
        warnings.append("Options final recommendations should remain blocked until option quotes are available.")

    return {
        "ok": bool(underlying_quote.get("ok")) and bool(metadata_result.get("ok")),
        "ticker": normalized_ticker,
        "timestamp": _now_iso(),
        "underlying_quote": underlying_quote,
        "metadata": metadata_result,
        "contracts_tested": contracts_tested,
        "quotes": quotes,
        "permissions_summary": permissions_summary,
        "warnings": warnings,
        "errors": errors,
    }


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
    options_quotes = diagnose_ibkr_option_quotes(normalized_ticker, max_contracts=3)

    historical_available = bool(historical_bars.get("ok"))
    quote_available = bool(quote_snapshot.get("ok") or delayed_quote_snapshot.get("ok") or delayed_frozen_quote_snapshot.get("ok"))
    options_metadata_available = bool((options_metadata.get("data") or {}).get("metadata"))
    options_quotes_available = bool((options_quotes.get("permissions_summary") or {}).get("option_quotes_available"))

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
