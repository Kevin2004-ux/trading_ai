from __future__ import annotations

from copy import deepcopy


_DEFAULT_SCAN_PROFILES = {
    "momentum_breakout": {
        "name": "momentum_breakout",
        "description": "Find strong stocks breaking out near recent highs.",
        "hard_constraints": {
            "minimum_relative_volume": 1.2,
            "require_price_above_sma_20": True,
            "require_price_above_sma_50": True,
            "minimum_risk_reward": 2.0,
            "minimum_score_to_recommend": 80,
        },
        "strategy_preferences": {
            "relative_volume_target": 1.8,
            "high_20_proximity_percent": 0.015,
            "daily_return_target": 0.01,
            "reward_trend_strength": True,
        },
        "minimum_score_to_recommend": 84,
        "minimum_score_to_watchlist": 72,
        "max_results": 10,
    },
    "trend_pullback": {
        "name": "trend_pullback",
        "description": "Find stocks in uptrends pulling back near support.",
        "hard_constraints": {
            "minimum_relative_volume": 1.0,
            "require_price_above_sma_20": False,
            "require_price_above_sma_50": True,
            "minimum_risk_reward": 2.0,
            "minimum_score_to_recommend": 78,
        },
        "strategy_preferences": {
            "pullback_to_sma20_distance_percent": 0.025,
            "relative_volume_target": 1.15,
            "daily_return_floor": -0.01,
            "reward_sma50_trend": True,
        },
        "minimum_score_to_recommend": 80,
        "minimum_score_to_watchlist": 68,
        "max_results": 10,
    },
    "oversold_reversal": {
        "name": "oversold_reversal",
        "description": "Find liquid stocks that are oversold but beginning to recover.",
        "hard_constraints": {
            "minimum_relative_volume": 1.0,
            "require_price_above_sma_20": False,
            "require_price_above_sma_50": False,
            "maximum_atr_percent": 0.10,
            "minimum_risk_reward": 2.0,
            "minimum_score_to_recommend": 76,
        },
        "strategy_preferences": {
            "oversold_rsi_threshold": 38,
            "reclaim_sma20_bonus": True,
            "relative_volume_target": 1.1,
            "daily_return_recovery_target": 0.005,
        },
        "minimum_score_to_recommend": 79,
        "minimum_score_to_watchlist": 66,
        "max_results": 10,
    },
    "relative_strength": {
        "name": "relative_strength",
        "description": "Find stocks outperforming the market or sector.",
        "hard_constraints": {
            "minimum_relative_volume": 1.3,
            "require_price_above_sma_20": True,
            "require_price_above_sma_50": True,
            "minimum_risk_reward": 2.0,
            "minimum_score_to_recommend": 82,
        },
        "strategy_preferences": {
            "relative_volume_target": 1.7,
            "daily_return_target": 0.012,
            "distance_from_sma50_target": 0.03,
            "reward_trend_strength": True,
        },
        "minimum_score_to_recommend": 85,
        "minimum_score_to_watchlist": 72,
        "max_results": 10,
    },
    "catalyst_watch": {
        "name": "catalyst_watch",
        "description": "Find liquid stocks with catalyst potential even if technical setup is not perfect yet.",
        "hard_constraints": {
            "minimum_relative_volume": 0.9,
            "require_price_above_sma_20": False,
            "require_price_above_sma_50": False,
            "minimum_risk_reward": 2.0,
            "maximum_atr_percent": 0.12,
            "minimum_score_to_recommend": 78,
        },
        "strategy_preferences": {
            "relative_volume_target": 1.1,
            "allow_watchlist_bias": True,
            "daily_return_target": 0.004,
            "reward_liquidity": True,
        },
        "minimum_score_to_recommend": 88,
        "minimum_score_to_watchlist": 62,
        "max_results": 12,
    },
}


def get_default_scan_profiles() -> dict:
    return deepcopy(_DEFAULT_SCAN_PROFILES)


def get_scan_profile(profile_name: str) -> dict:
    profiles = get_default_scan_profiles()
    profile = profiles.get(str(profile_name or "").strip())
    if profile is None:
        return {
            "ok": False,
            "error": f"Unknown scan profile: {profile_name}",
            "available_profiles": sorted(profiles.keys()),
        }
    return {"ok": True, "profile": profile}
