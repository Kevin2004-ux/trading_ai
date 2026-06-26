from __future__ import annotations

import json
from typing import Any


REFINEMENT_PROMPT_VERSION = "scan_refinement_prompt_v1"


def build_refinement_system_prompt() -> str:
    return (
        "You propose exactly one bounded research-plan adjustment for a paper-trading scan. "
        "You cannot approve or recommend trades. You cannot weaken deterministic gates, force a trade, "
        "change the user's instrument scope, add unrelated custom tickers, disable data quality, disable option "
        "quote/IV/Greeks/liquidity/spread/fill/DTE/risk checks, enable brokerage execution, or enable auto-log. "
        "Stop when provider data is unavailable or when sufficient legitimate ideas already exist. Prefer a materially "
        "distinct search over repeating the same plan. Return only the structured RefinementProposalModel schema. "
        "PolicyValidator and refinement scope locks remain authoritative."
    )


def build_refinement_user_payload(
    *,
    initial_plan: dict,
    current_plan: dict,
    pass_evaluation: dict,
    prior_pass_summaries: list[dict],
    remaining_pass_budget: int,
    runtime_context: dict | None = None,
) -> str:
    return json.dumps(
        {
            "prompt_version": REFINEMENT_PROMPT_VERSION,
            "initial_plan_scope": {
                "objective": initial_plan.get("objective"),
                "requested_instrument": initial_plan.get("requested_instrument"),
                "time_horizon": initial_plan.get("time_horizon"),
                "universes": initial_plan.get("universes"),
                "custom_tickers": initial_plan.get("custom_tickers"),
                "include_options": initial_plan.get("include_options"),
                "prefer_options": initial_plan.get("prefer_options"),
                "research_preferences": initial_plan.get("research_preferences"),
            },
            "current_plan_scope": {
                "universes": current_plan.get("universes"),
                "profiles": current_plan.get("profiles"),
                "max_tickers": current_plan.get("max_tickers"),
                "max_candidates": current_plan.get("max_candidates"),
                "option_preferences": current_plan.get("option_preferences"),
                "soft_adjustments": current_plan.get("soft_adjustments"),
            },
            "pass_evaluation": pass_evaluation,
            "prior_pass_summaries": prior_pass_summaries,
            "remaining_pass_budget": remaining_pass_budget,
            "runtime_context": {
                key: value
                for key, value in (runtime_context or {}).items()
                if isinstance(value, (str, int, float, bool)) and "key" not in str(key).lower()
            },
        },
        sort_keys=True,
    )
