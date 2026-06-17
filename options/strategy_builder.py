from __future__ import annotations

import math
from copy import deepcopy
from typing import Any

from options.strategy_evaluator import evaluate_option_strategy
from options.strategy_selector import select_best_option_strategy
from realtime.options_chain import normalize_options_chain


def _safe_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(numeric) or math.isinf(numeric):
        return None
    return numeric


def _mid(contract: dict) -> float | None:
    mid = _safe_float(contract.get("mid"))
    bid = _safe_float(contract.get("bid"))
    ask = _safe_float(contract.get("ask"))
    if mid is None and bid is not None and ask is not None:
        mid = round((bid + ask) / 2.0, 4)
    return mid


def _price_for_action(contract: dict, action: str) -> float | None:
    if action == "sell":
        return _safe_float(contract.get("bid")) or _mid(contract)
    return _safe_float(contract.get("ask")) or _mid(contract)


def _contract_id(contract: dict) -> str:
    return str(contract.get("option_contract") or contract.get("ticker") or "").upper()


def _clone_contract(contract: dict) -> dict:
    cloned = deepcopy(contract)
    cloned["option_contract"] = _contract_id(cloned)
    return cloned


def _leg(action: str, contract: dict, quantity: int = 1) -> dict:
    return {
        "action": action,
        "quantity": quantity,
        "option_contract": _contract_id(contract),
        "contract": _clone_contract(contract),
    }


def _current_price(underlying_view: dict) -> float | None:
    return (
        _safe_float(underlying_view.get("current_price"))
        or _safe_float(underlying_view.get("entry_price"))
        or _safe_float(underlying_view.get("underlying_price"))
    )


def _underlying_bias(underlying_view: dict) -> str:
    value = str(underlying_view.get("option_bias") or underlying_view.get("bias") or underlying_view.get("direction") or "long").lower()
    if value in {"long", "bullish", "up", "upside"}:
        return "bullish"
    if value in {"short", "bearish", "down", "downside"}:
        return "bearish"
    return "neutral"


def _contracts_by_type(chain: list[dict], option_type: str) -> list[dict]:
    return sorted(
        [item for item in chain if str(item.get("option_type", "")).lower() == option_type and _safe_float(item.get("strike")) is not None],
        key=lambda item: (_safe_float(item.get("days_to_expiration")) or 9999, _safe_float(item.get("strike")) or 0.0),
    )


def _nearest_contract(contracts: list[dict], price: float | None, prefer: str) -> dict | None:
    if not contracts:
        return None
    if price is None:
        return contracts[0]
    candidates = contracts
    if prefer == "above":
        candidates = [item for item in contracts if (_safe_float(item.get("strike")) or 0) >= price] or contracts
    elif prefer == "below":
        candidates = [item for item in contracts if (_safe_float(item.get("strike")) or 0) <= price] or contracts
    return min(candidates, key=lambda item: abs((_safe_float(item.get("strike")) or price) - price))


def _same_expiration_higher(contracts: list[dict], long_leg: dict) -> dict | None:
    expiration = long_leg.get("expiration")
    strike = _safe_float(long_leg.get("strike"))
    candidates = [
        item for item in contracts
        if item.get("expiration") == expiration and (_safe_float(item.get("strike")) or 0) > (strike or 0)
    ]
    return min(candidates, key=lambda item: _safe_float(item.get("strike")) or 0.0) if candidates else None


def _same_expiration_lower(contracts: list[dict], long_leg: dict) -> dict | None:
    expiration = long_leg.get("expiration")
    strike = _safe_float(long_leg.get("strike"))
    candidates = [
        item for item in contracts
        if item.get("expiration") == expiration and (_safe_float(item.get("strike")) or 0) < (strike or 0)
    ]
    return max(candidates, key=lambda item: _safe_float(item.get("strike")) or 0.0) if candidates else None


def _aggregate_context(legs: list[dict]) -> tuple[dict, dict]:
    iv_contexts = []
    greeks = {"delta": 0.0, "gamma": 0.0, "theta": 0.0, "vega": 0.0, "rho": 0.0}
    for leg in legs:
        contract = leg["contract"]
        if isinstance(contract.get("iv_context"), dict):
            iv_contexts.append(contract["iv_context"])
        elif contract.get("iv_rank") is not None:
            iv_contexts.append({"iv_context": "provider_supplied", "iv_rank": contract.get("iv_rank")})
        multiplier = 1.0 if leg["action"] == "buy" else -1.0
        for key in greeks:
            value = _safe_float(contract.get(key))
            if value is not None:
                greeks[key] += value * multiplier
    return (
        {"legs": iv_contexts, "summary": iv_contexts[0] if iv_contexts else {}},
        {key: round(value, 4) for key, value in greeks.items()},
    )


def _finalize_strategy(strategy: dict, underlying_view: dict, config: dict | None = None) -> dict:
    evaluation = evaluate_option_strategy(strategy, underlying_view=underlying_view, config=config)
    finalized = deepcopy(strategy)
    finalized["evaluation"] = evaluation
    finalized["status"] = evaluation.get("status", finalized.get("status", "blocked"))
    finalized["score"] = evaluation.get("score")
    finalized["risk"] = evaluation
    finalized["reasons"] = list(finalized.get("reasons", [])) + list(evaluation.get("reasons", []))
    finalized["warnings"] = list(finalized.get("warnings", [])) + list(evaluation.get("warnings", []))
    if evaluation.get("errors"):
        finalized["errors"] = list(finalized.get("errors", [])) + list(evaluation.get("errors", []))
    return finalized


def _base_strategy(strategy_type: str, direction: str, legs: list[dict], underlying_view: dict) -> dict:
    iv_context, greeks = _aggregate_context(legs)
    dtes = [_safe_float(leg["contract"].get("days_to_expiration")) for leg in legs]
    dtes = [item for item in dtes if item is not None]
    return {
        "strategy_type": strategy_type,
        "direction": direction,
        "underlying_ticker": str(underlying_view.get("ticker") or underlying_view.get("underlying_ticker") or "").upper(),
        "underlying_view": deepcopy(underlying_view),
        "legs": legs,
        "days_to_expiration": int(min(dtes)) if dtes else None,
        "estimated_fill": {},
        "iv_context": iv_context,
        "greeks": greeks,
        "reasons": [],
        "warnings": [],
        "errors": [],
    }


def build_long_call_candidate(call_contract: dict, underlying_view: dict, config: dict | None = None) -> dict:
    ask = _price_for_action(call_contract, "buy")
    strike = _safe_float(call_contract.get("strike"))
    strategy = _base_strategy("long_call", "bullish", [_leg("buy", call_contract)], underlying_view)
    strategy.update(
        {
            "net_debit": ask,
            "net_credit": None,
            "max_loss": ask,
            "max_profit": None,
            "breakeven": (strike + ask) if strike is not None and ask is not None else None,
            "estimated_fill": {"debit": ask, "method": "conservative_buy_at_ask"},
        }
    )
    return _finalize_strategy(strategy, underlying_view, config=config)


def build_long_put_candidate(put_contract: dict, underlying_view: dict, config: dict | None = None) -> dict:
    ask = _price_for_action(put_contract, "buy")
    strike = _safe_float(put_contract.get("strike"))
    strategy = _base_strategy("long_put", "bearish", [_leg("buy", put_contract)], underlying_view)
    strategy.update(
        {
            "net_debit": ask,
            "net_credit": None,
            "max_loss": ask,
            "max_profit": (strike - ask) if strike is not None and ask is not None else None,
            "breakeven": (strike - ask) if strike is not None and ask is not None else None,
            "estimated_fill": {"debit": ask, "method": "conservative_buy_at_ask"},
        }
    )
    return _finalize_strategy(strategy, underlying_view, config=config)


def build_bull_call_debit_spread_candidate(long_call: dict, short_call: dict, underlying_view: dict, config: dict | None = None) -> dict:
    debit = None
    long_ask = _price_for_action(long_call, "buy")
    short_bid = _price_for_action(short_call, "sell")
    lower = _safe_float(long_call.get("strike"))
    upper = _safe_float(short_call.get("strike"))
    if long_ask is not None and short_bid is not None:
        debit = round(max(long_ask - short_bid, 0.0), 4)
    width = (upper - lower) if lower is not None and upper is not None else None
    strategy = _base_strategy("bull_call_debit_spread", "bullish", [_leg("buy", long_call), _leg("sell", short_call)], underlying_view)
    strategy.update(
        {
            "net_debit": debit,
            "net_credit": None,
            "max_loss": debit,
            "max_profit": round(width - debit, 4) if width is not None and debit is not None else None,
            "breakeven": round(lower + debit, 4) if lower is not None and debit is not None else None,
            "estimated_fill": {"debit": debit, "method": "buy_long_at_ask_sell_short_at_bid"},
        }
    )
    return _finalize_strategy(strategy, underlying_view, config=config)


def build_bear_put_debit_spread_candidate(long_put: dict, short_put: dict, underlying_view: dict, config: dict | None = None) -> dict:
    debit = None
    long_ask = _price_for_action(long_put, "buy")
    short_bid = _price_for_action(short_put, "sell")
    high = _safe_float(long_put.get("strike"))
    low = _safe_float(short_put.get("strike"))
    if long_ask is not None and short_bid is not None:
        debit = round(max(long_ask - short_bid, 0.0), 4)
    width = (high - low) if high is not None and low is not None else None
    strategy = _base_strategy("bear_put_debit_spread", "bearish", [_leg("buy", long_put), _leg("sell", short_put)], underlying_view)
    strategy.update(
        {
            "net_debit": debit,
            "net_credit": None,
            "max_loss": debit,
            "max_profit": round(width - debit, 4) if width is not None and debit is not None else None,
            "breakeven": round(high - debit, 4) if high is not None and debit is not None else None,
            "estimated_fill": {"debit": debit, "method": "buy_long_at_ask_sell_short_at_bid"},
        }
    )
    return _finalize_strategy(strategy, underlying_view, config=config)


def build_credit_spread_research_candidate(short_leg: dict, long_leg: dict, underlying_view: dict, strategy_type: str, config: dict | None = None) -> dict:
    credit = None
    short_bid = _price_for_action(short_leg, "sell")
    long_ask = _price_for_action(long_leg, "buy")
    short_strike = _safe_float(short_leg.get("strike"))
    long_strike = _safe_float(long_leg.get("strike"))
    if short_bid is not None and long_ask is not None:
        credit = round(max(short_bid - long_ask, 0.0), 4)
    width = abs((long_strike or 0.0) - (short_strike or 0.0)) if short_strike is not None and long_strike is not None else None
    direction = "bearish" if "call" in strategy_type else "bullish"
    breakeven = None
    if credit is not None and short_strike is not None:
        breakeven = short_strike + credit if "call" in strategy_type else short_strike - credit
    strategy = _base_strategy(strategy_type, direction, [_leg("sell", short_leg), _leg("buy", long_leg)], underlying_view)
    strategy.update(
        {
            "net_debit": None,
            "net_credit": credit,
            "max_loss": round(width - credit, 4) if width is not None and credit is not None else None,
            "max_profit": credit,
            "breakeven": breakeven,
            "estimated_fill": {"credit": credit, "method": "sell_short_at_bid_buy_long_at_ask"},
            "warnings": ["Credit spreads are research-only until margin and assignment risk rules are implemented."],
        }
    )
    return _finalize_strategy(strategy, underlying_view, config=config)


def _covered_call_candidate(call_contract: dict, underlying_view: dict, config: dict | None = None) -> dict:
    bid = _price_for_action(call_contract, "sell")
    strike = _safe_float(call_contract.get("strike"))
    entry = _current_price(underlying_view)
    strategy = _base_strategy("covered_call_research", "neutral", [_leg("sell", call_contract)], underlying_view)
    strategy.update(
        {
            "net_debit": None,
            "net_credit": bid,
            "max_loss": None,
            "max_profit": (strike - entry + bid) if None not in (strike, entry, bid) else None,
            "breakeven": (entry - bid) if entry is not None and bid is not None else None,
            "estimated_fill": {"credit": bid, "method": "research_only_short_call_at_bid"},
            "warnings": ["Covered calls require verified share ownership and remain research-only."],
        }
    )
    return _finalize_strategy(strategy, underlying_view, config=config)


def _cash_secured_put_candidate(put_contract: dict, underlying_view: dict, config: dict | None = None) -> dict:
    bid = _price_for_action(put_contract, "sell")
    strike = _safe_float(put_contract.get("strike"))
    strategy = _base_strategy("cash_secured_put_research", "bullish", [_leg("sell", put_contract)], underlying_view)
    strategy.update(
        {
            "net_debit": None,
            "net_credit": bid,
            "max_loss": (strike - bid) if strike is not None and bid is not None else None,
            "max_profit": bid,
            "breakeven": (strike - bid) if strike is not None and bid is not None else None,
            "estimated_fill": {"credit": bid, "method": "research_only_short_put_at_bid"},
            "warnings": ["Cash-secured puts require account cash/margin context and remain research-only."],
        }
    )
    return _finalize_strategy(strategy, underlying_view, config=config)


def build_option_strategy_candidates(
    underlying_ticker: str,
    underlying_view: dict,
    option_chain: list[dict],
    config: dict | None = None,
) -> dict:
    ticker = str(underlying_ticker or underlying_view.get("ticker") or "").upper()
    normalized_chain = normalize_options_chain(option_chain or [])
    warnings: list[str] = []
    errors: list[str] = []
    if not normalized_chain:
        return {
            "ok": False,
            "ticker": ticker,
            "underlying_view": underlying_view,
            "strategies": [],
            "selected_strategy": None,
            "summary": {"paper_eligible_count": 0, "research_only_count": 0, "blocked_count": 0},
            "warnings": [],
            "errors": ["Option chain is empty or malformed."],
        }

    price = _current_price(underlying_view)
    calls = _contracts_by_type(normalized_chain, "call")
    puts = _contracts_by_type(normalized_chain, "put")
    strategies: list[dict] = []
    long_call = _nearest_contract(calls, price, "above")
    long_put = _nearest_contract(puts, price, "below")
    if long_call:
        strategies.append(build_long_call_candidate(long_call, underlying_view, config=config))
        short_call = _same_expiration_higher(calls, long_call)
        if short_call:
            strategies.append(build_bull_call_debit_spread_candidate(long_call, short_call, underlying_view, config=config))
            strategies.append(build_credit_spread_research_candidate(long_call, short_call, underlying_view, "call_credit_spread_research", config=config))
        strategies.append(_covered_call_candidate(long_call, underlying_view, config=config))
    else:
        warnings.append("No call contract was available for call-based strategy construction.")

    if long_put:
        strategies.append(build_long_put_candidate(long_put, underlying_view, config=config))
        short_put = _same_expiration_lower(puts, long_put)
        if short_put:
            strategies.append(build_bear_put_debit_spread_candidate(long_put, short_put, underlying_view, config=config))
            strategies.append(build_credit_spread_research_candidate(long_put, short_put, underlying_view, "put_credit_spread_research", config=config))
        strategies.append(_cash_secured_put_candidate(long_put, underlying_view, config=config))
    else:
        warnings.append("No put contract was available for put-based strategy construction.")

    selection = select_best_option_strategy(strategies, config=config)
    return {
        "ok": bool(strategies),
        "ticker": ticker,
        "underlying_view": deepcopy(underlying_view),
        "strategies": strategies,
        "selected_strategy": selection.get("selected_strategy"),
        "selection": selection,
        "summary": {
            "strategy_count": len(strategies),
            "paper_eligible_count": selection.get("paper_eligible_count", 0),
            "research_only_count": selection.get("research_only_count", 0),
            "blocked_count": selection.get("blocked_count", 0),
            "selection_reason": selection.get("selection_reason"),
            "underlying_bias": _underlying_bias(underlying_view),
        },
        "warnings": warnings,
        "errors": errors,
    }

