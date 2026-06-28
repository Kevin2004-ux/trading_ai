from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


SCAN_PLAN_VERSION = "scan_plan_v1"


class OptionPreferences(BaseModel):
    model_config = ConfigDict(extra="allow")

    min_dte: Any = 14
    max_dte: Any = 56
    max_contracts_per_ticker: Any = 3
    max_option_premium: Any | None = None
    allowed_strategy_types: list[str] = Field(default_factory=list)


class ResearchPreferences(BaseModel):
    model_config = ConfigDict(extra="allow")

    include_news: bool = False
    include_sec_filings: bool = False
    include_earnings_transcripts: bool = False
    include_short_interest: bool = True


class SoftAdjustments(BaseModel):
    model_config = ConfigDict(extra="allow")

    profile_weights: dict[str, Any] = Field(default_factory=dict)
    opportunity_weights: dict[str, Any] = Field(default_factory=dict)
    minimum_relative_volume: Any | None = None
    minimum_opportunity_score: Any | None = None
    breakout_proximity_percent: Any | None = None
    pullback_distance_percent: Any | None = None
    min_stock_price: Any | None = None
    max_stock_price: Any | None = None


class RefinementPreferences(BaseModel):
    model_config = ConfigDict(extra="allow")

    max_passes: Any = 1
    allow_broader_universe_on_retry: bool = True
    allow_profile_change_on_retry: bool = True


class ScanPlan(BaseModel):
    model_config = ConfigDict(extra="allow")

    plan_version: str = SCAN_PLAN_VERSION
    requested_instrument: str = "stocks"
    objective: str = "best_ideas"
    time_horizon: str = "swing"
    direction: str = "long"
    universes: list[str] = Field(default_factory=lambda: ["large_cap"])
    custom_tickers: list[str] = Field(default_factory=list)
    profiles: list[str] = Field(default_factory=list)
    max_tickers: Any = 100
    max_candidates: Any = 20
    max_final_trades: Any = 5
    min_final_trades: Any = 0
    include_market_regime: bool = True
    include_relative_strength: bool = True
    include_catalysts: bool = True
    include_portfolio_risk: bool = True
    include_position_sizing: bool = True
    include_options: bool = False
    prefer_options: bool = False
    option_preferences: OptionPreferences = Field(default_factory=OptionPreferences)
    research_preferences: ResearchPreferences = Field(default_factory=ResearchPreferences)
    soft_adjustments: SoftAdjustments = Field(default_factory=SoftAdjustments)
    refinement: RefinementPreferences = Field(default_factory=RefinementPreferences)
    reasoning_summary: str = ""
    created_by: str = "deterministic_default"
    request_id: str | None = None


def plan_to_dict(plan: ScanPlan | dict) -> dict:
    if isinstance(plan, ScanPlan):
        return plan.model_dump(mode="json")
    if isinstance(plan, dict):
        parsed = ScanPlan.model_validate(plan)
        return parsed.model_dump(mode="json")
    parsed = ScanPlan.model_validate({})
    return parsed.model_dump(mode="json")


def build_default_scan_plan(
    objective: str = "best_ideas",
    requested_instrument: str = "stocks",
    ticker: str | None = None,
) -> ScanPlan:
    instrument = str(requested_instrument or "stocks").strip().lower()
    if instrument not in {"stocks", "options", "both"}:
        instrument = "stocks"

    normalized_objective = str(objective or "best_ideas").strip().lower()
    universes = ["large_cap", "active", "tech"]
    custom_tickers: list[str] = []
    max_tickers = 100
    profiles: list[str] = []
    include_options = instrument in {"options", "both"}
    prefer_options = instrument == "options"

    if normalized_objective == "ticker_review" or ticker:
        universes = ["custom"]
        custom_tickers = [ticker] if ticker else []
        max_tickers = 1
    elif normalized_objective == "options_research":
        instrument = "options"
        include_options = True
        prefer_options = True
        universes = ["large_cap", "active"]
    elif normalized_objective == "watchlist":
        universes = ["large_cap", "active", "growth"]
    elif normalized_objective == "explain_no_trades":
        normalized_objective = "best_ideas"
        universes = ["large_cap", "active", "tech"]

    return ScanPlan(
        requested_instrument=instrument,
        objective=normalized_objective,
        universes=universes,
        custom_tickers=custom_tickers,
        profiles=profiles,
        max_tickers=max_tickers,
        include_options=include_options,
        prefer_options=prefer_options,
        created_by="deterministic_default",
    )
