"""Lazy exports for analytics helpers.

Keeping package imports lazy avoids circular imports between options evaluation,
market-regime analysis, and scanner modules.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any


_EXPORT_MODULES = {
    "analyze_index_trend": "analytics.market_regime",
    "analyze_market_breadth": "analytics.market_regime",
    "analyze_volatility_regime": "analytics.market_regime",
    "apply_regime_to_trade_selection": "analytics.market_regime",
    "determine_market_regime": "analytics.market_regime",
    "get_market_regime_snapshot": "analytics.market_regime",
    "black_scholes_value": "analytics.options_mispricing",
    "calculate_expected_move_context": "analytics.options_mispricing",
    "estimate_historical_volatility": "analytics.options_mispricing",
    "evaluate_option_mispricing": "analytics.options_mispricing",
    "rank_options_by_value": "analytics.options_mispricing",
    "analyze_sector_strength": "analytics.relative_strength",
    "analyze_stock_relative_strength": "analytics.relative_strength",
    "apply_relative_strength_to_candidate": "analytics.relative_strength",
    "calculate_relative_performance": "analytics.relative_strength",
    "get_relative_strength_snapshot": "analytics.relative_strength",
    "analyze_profile_performance": "analytics.statistical_brain",
    "analyze_setup_performance": "analytics.statistical_brain",
    "analyze_ticker_history": "analytics.statistical_brain",
    "calculate_expectancy": "analytics.statistical_brain",
    "enrich_candidate_with_statistics": "analytics.statistical_brain",
    "score_statistical_confidence": "analytics.statistical_brain",
}

__all__ = sorted(_EXPORT_MODULES)


def __getattr__(name: str) -> Any:
    module_name = _EXPORT_MODULES.get(name)
    if module_name is None:
        raise AttributeError(f"module 'analytics' has no attribute {name!r}")
    module = import_module(module_name)
    value = getattr(module, name)
    globals()[name] = value
    return value
