import math

import numpy as np

try:
    from scipy.stats import norm
except ImportError:  # pragma: no cover - depends on local environment
    norm = None

from analytics.options_mispricing import (
    estimate_historical_volatility,
    evaluate_option_mispricing,
)
from engine.constraint_engine import evaluate_option_constraints
from realtime.options_chain import calculate_option_metrics, normalize_options_chain

def black_scholes_call_price(S, K, T, r, sigma):
    """Calculates the price of a European call option using Black-Scholes."""
    if T <= 0: return max(S - K, 0.0)
    if sigma <= 0: return max(S - K, 0.0)
    d1 = (np.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * np.sqrt(T))
    d2 = d1 - sigma * np.sqrt(T)
    cdf = norm.cdf if norm is not None else lambda value: 0.5 * (1.0 + math.erf(value / math.sqrt(2.0)))
    price = (S * cdf(d1) - K * np.exp(-r * T) * cdf(d2))
    return price

def evaluate_options(S0, R_adj, sigma_imp, r_f=0.05, num_strategies=5, aggressiveness="balanced"):
    """
    Evaluates potential call option strategies based on the forecast, now factoring in
    an aggressiveness parameter.
    """
    print(f"  Evaluating options strategies with '{aggressiveness}' profile...")

    # Define strike price ranges based on aggressiveness
    if R_adj <= 0: # If forecast is not bullish, don't recommend long calls
        return []
    
    strike_range = {
        "conservative": np.arange(-0.05, 0.051, 0.01),  # Near-the-money
        "balanced": np.arange(-0.02, 0.101, 0.015),   # Slightly out-of-the-money
        "aggressive": np.arange(0.05, 0.151, 0.02)     # Further out-of-the-money
    }
    
    strikes = [S0 * (1 + p) for p in strike_range.get(aggressiveness, strike_range["balanced"])]
    expiries_days = [7, 15, 30, 60]
    results = []
    
    S1_expected = S0 * (1 + R_adj) # Expected price at expiry

    for T_days in expiries_days:
        T_years = T_days / 365.25
        for K in strikes:
            premium = black_scholes_call_price(S0, K, T_years, r_f, sigma_imp)
            if premium < 0.01: continue # Skip worthless options

            expected_payoff = max(S1_expected - K, 0)
            expected_pnl = expected_payoff - premium
            # Simple risk/reward: potential profit divided by max loss (the premium)
            risk_reward_ratio = expected_pnl / premium if premium > 0 else 0
            
            results.append({
                "strategy_type": "Long Call", "strike_price": K, "expiry_days": T_days,
                "premium": premium, "expected_pnl_per_share": expected_pnl,
                "risk_reward_ratio": risk_reward_ratio
            })

    if not results:
        return []
        
    # Sort by risk/reward ratio and return the top N strategies
    sorted_results = sorted(results, key=lambda x: x['risk_reward_ratio'], reverse=True)
    top_strategies = sorted_results[:num_strategies]
    
    print(f"  Found {len(top_strategies)} promising option strategies.")
    return top_strategies


def _safe_float(value):
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _underlying_constraint_result(underlying_candidate: dict) -> dict:
    return {
        "passed": bool(underlying_candidate.get("passed")),
        "recommendation_status": str(underlying_candidate.get("recommendation_status", "rejected")).lower(),
        "score": _safe_float(underlying_candidate.get("score")),
    }


def _rank_option_candidates(candidates: list[dict]) -> list[dict]:
    ranked = sorted(
        candidates,
        key=lambda candidate: (
            1 if str(candidate.get("recommendation_status", "rejected")).lower() == "recommendable" else 0,
            _safe_float(candidate.get("mispricing_score")) or 0.0,
            _safe_float(candidate.get("score")) or 0.0,
            _safe_float(candidate.get("risk_reward")) or 0.0,
            _safe_float(candidate.get("open_interest")) or 0.0,
            _safe_float(candidate.get("volume")) or 0.0,
            -(_safe_float(candidate.get("spread_percent")) or 0.0),
            -(_safe_float(candidate.get("breakeven_move_percent")) or 0.0),
        ),
        reverse=True,
    )
    for index, candidate in enumerate(ranked, start=1):
        candidate["rank"] = index
    return ranked


def evaluate_option_chain_for_trade(
    underlying_candidate: dict,
    option_chain: list[dict],
    strategy: str = "long_call",
    max_contracts: int = 5,
) -> dict:
    ticker = str(underlying_candidate.get("ticker", "")).upper()
    direction = str(underlying_candidate.get("direction", "long")).lower()
    if strategy != "long_call":
        return {
            "ok": False,
            "underlying_ticker": ticker,
            "strategy": strategy,
            "best_option_candidates": [],
            "watchlist_option_candidates": [],
            "rejected_option_candidates": [],
            "summary": {
                "contracts_evaluated": 0,
                "contracts_passed": 0,
                "message": "Only long_call option research is supported right now.",
            },
            "errors": ["Only long_call option research is supported right now."],
        }
    if direction != "long":
        return {
            "ok": False,
            "underlying_ticker": ticker,
            "strategy": strategy,
            "best_option_candidates": [],
            "watchlist_option_candidates": [],
            "rejected_option_candidates": [],
            "summary": {
                "contracts_evaluated": 0,
                "contracts_passed": 0,
                "message": "Only long stock candidates can be mapped to long-call research.",
            },
            "errors": ["Only long stock candidates can be mapped to long-call research."],
        }

    normalized_chain = normalize_options_chain(option_chain)
    if not normalized_chain:
        return {
            "ok": False,
            "underlying_ticker": ticker,
            "strategy": strategy,
            "best_option_candidates": [],
            "watchlist_option_candidates": [],
            "rejected_option_candidates": [],
            "summary": {
                "contracts_evaluated": 0,
                "contracts_passed": 0,
                "message": "Option chain is empty or malformed.",
            },
            "errors": ["Option chain is empty or malformed."],
        }

    entry_price = _safe_float(underlying_candidate.get("entry_price"))
    target_price = _safe_float(underlying_candidate.get("target_price"))
    stop_loss = _safe_float(underlying_candidate.get("stop_loss"))
    current_price = _safe_float(underlying_candidate.get("current_price")) or entry_price
    if current_price is None:
        current_price = entry_price or 0.0

    underlying_result = _underlying_constraint_result(underlying_candidate)
    evaluated_candidates = []
    historical_volatility_result = estimate_historical_volatility(
        bars=underlying_candidate.get("bars") if isinstance(underlying_candidate.get("bars"), list) else None,
    )
    historical_volatility = (
        _safe_float(historical_volatility_result.get("historical_volatility"))
        if historical_volatility_result.get("ok")
        else None
    )

    for raw_option in normalized_chain:
        option_metrics = calculate_option_metrics(
            raw_option,
            underlying_price=current_price or 0.0,
            expected_target_price=target_price,
        )
        option_candidate = {
            **raw_option,
            **option_metrics,
            "asset_type": "option",
            "direction": "long",
            "strategy": strategy,
            "ticker": raw_option.get("option_contract") or raw_option.get("ticker"),
            "underlying_entry_price": entry_price,
            "underlying_target_price": target_price,
            "underlying_stop_loss": stop_loss,
            "expected_target_price": target_price,
        }

        premium = _safe_float(option_candidate.get("mid"))
        strike = _safe_float(option_candidate.get("strike"))
        option_type = str(option_candidate.get("option_type", "")).lower()
        expected_value_at_stop = None
        expected_profit_per_share = option_metrics.get("expected_profit_per_share")
        estimated_loss_per_share = None

        if premium is not None and strike is not None and stop_loss is not None and option_type == "call":
            expected_value_at_stop = max(stop_loss - strike, 0.0)
            estimated_loss_per_share = max(premium - expected_value_at_stop, 0.0)

        risk_reward = None
        if expected_profit_per_share is not None and estimated_loss_per_share not in (None, 0):
            risk_reward = expected_profit_per_share / estimated_loss_per_share if estimated_loss_per_share > 0 else None
        if risk_reward is None:
            risk_reward = 0.0

        option_candidate["expected_value_at_stop"] = expected_value_at_stop
        option_candidate["expected_profit_per_share"] = expected_profit_per_share
        option_candidate["expected_profit_per_contract"] = (
            expected_profit_per_share * 100.0 if expected_profit_per_share is not None else None
        )
        option_candidate["estimated_loss_per_share"] = estimated_loss_per_share
        option_candidate["estimated_loss_per_contract"] = (
            estimated_loss_per_share * 100.0 if estimated_loss_per_share is not None else None
        )
        option_candidate["risk_reward"] = risk_reward
        option_candidate["breakeven_realistic"] = bool(option_metrics.get("target_reaches_breakeven"))
        mispricing_context = evaluate_option_mispricing(
            option_candidate=option_candidate,
            underlying_candidate=underlying_candidate,
            historical_volatility=historical_volatility,
        )
        option_candidate["mispricing_context"] = mispricing_context
        option_candidate["mispricing_label"] = mispricing_context.get("mispricing_label")
        option_candidate["mispricing_score"] = mispricing_context.get("mispricing_score")

        constraint_result = evaluate_option_constraints(
            option_candidate,
            underlying_result=underlying_result,
        )
        option_candidate["passed"] = constraint_result["passed"]
        option_candidate["recommendation_status"] = constraint_result["recommendation_status"]
        option_candidate["score"] = constraint_result["score"]
        option_candidate["constraint_results"] = constraint_result["constraint_results"]
        option_candidate["failed_constraints"] = constraint_result["failed_constraints"]
        option_candidate["rejection_reason"] = constraint_result["rejection_reason"]
        evaluated_candidates.append(option_candidate)

    recommendable = _rank_option_candidates(
        [candidate for candidate in evaluated_candidates if candidate.get("recommendation_status") == "recommendable"]
    )
    watchlist = _rank_option_candidates(
        [candidate for candidate in evaluated_candidates if candidate.get("recommendation_status") == "watchlist"]
    )
    rejected = _rank_option_candidates(
        [candidate for candidate in evaluated_candidates if candidate.get("recommendation_status") == "rejected"]
    )

    best_option_candidates = recommendable[:max_contracts]
    summary_message = "Option chain evaluated successfully."
    if not best_option_candidates and watchlist:
        summary_message = "No option contracts passed recommendation thresholds, but watchlist alternatives were found."
    elif not best_option_candidates and not watchlist:
        summary_message = "No option contracts passed the objective option constraints."

    return {
        "ok": True,
        "underlying_ticker": ticker,
        "strategy": strategy,
        "best_option_candidates": best_option_candidates,
        "watchlist_option_candidates": watchlist[:max_contracts],
        "rejected_option_candidates": rejected,
        "summary": {
            "contracts_evaluated": len(evaluated_candidates),
            "contracts_passed": len(best_option_candidates),
            "message": summary_message,
        },
        "errors": [],
    }
