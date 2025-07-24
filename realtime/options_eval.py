import numpy as np
from scipy.stats import norm

def black_scholes_call_price(S, K, T, r, sigma):
    """Calculates the price of a European call option using Black-Scholes."""
    if T <= 0: return max(S - K, 0.0)
    if sigma <= 0: return max(S - K, 0.0)
    d1 = (np.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * np.sqrt(T))
    d2 = d1 - sigma * np.sqrt(T)
    price = (S * norm.cdf(d1) - K * np.exp(-r * T) * norm.cdf(d2))
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