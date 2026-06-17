from __future__ import annotations

from copy import deepcopy
from typing import Any

from options.strategy_evaluator import evaluate_option_strategy


STATUS_PRIORITY = {
    "paper_eligible": 3,
    "research_only": 2,
    "blocked": 1,
}


def _safe_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _normalized_strategy(strategy: dict, config: dict | None = None) -> dict:
    enriched = deepcopy(strategy)
    evaluation = enriched.get("evaluation")
    if not isinstance(evaluation, dict):
        evaluation = evaluate_option_strategy(enriched, underlying_view=enriched.get("underlying_view"), config=config)
        enriched["evaluation"] = evaluation
    enriched["status"] = evaluation.get("status", enriched.get("status", "blocked"))
    enriched["score"] = evaluation.get("score", enriched.get("score", 0.0))
    enriched["reasons"] = list(enriched.get("reasons", [])) + list(evaluation.get("reasons", []))
    enriched["warnings"] = list(enriched.get("warnings", [])) + list(evaluation.get("warnings", []))
    if evaluation.get("errors"):
        enriched["errors"] = list(enriched.get("errors", [])) + list(evaluation.get("errors", []))
    return enriched


def compare_option_strategies(
    strategies: list[dict],
    config: dict | None = None,
) -> dict:
    normalized = [_normalized_strategy(strategy, config=config) for strategy in strategies or [] if isinstance(strategy, dict)]
    ranked = sorted(
        normalized,
        key=lambda item: (
            STATUS_PRIORITY.get(str(item.get("status", "blocked")).lower(), 0),
            _safe_float(item.get("score")),
            _safe_float(item.get("max_profit")),
            -_safe_float(item.get("max_loss")),
        ),
        reverse=True,
    )
    for index, item in enumerate(ranked, start=1):
        item["rank"] = index

    return {
        "ok": bool(ranked),
        "ranked_strategies": ranked,
        "paper_eligible_count": sum(1 for item in ranked if item.get("status") == "paper_eligible"),
        "research_only_count": sum(1 for item in ranked if item.get("status") == "research_only"),
        "blocked_count": sum(1 for item in ranked if item.get("status") == "blocked"),
        "warnings": [],
        "errors": [] if ranked else ["No option strategies were available to compare."],
    }


def select_best_option_strategy(
    strategies: list[dict],
    config: dict | None = None,
) -> dict:
    comparison = compare_option_strategies(strategies, config=config)
    ranked = comparison.get("ranked_strategies", [])
    selected = ranked[0] if ranked else None
    if selected is None:
        reason = "No option strategies were available."
    elif selected.get("status") == "paper_eligible":
        reason = f"Selected {selected.get('strategy_type')} because it passed all option strategy gates."
    elif selected.get("status") == "research_only":
        reason = f"No paper-eligible strategy was available; returning best research-only {selected.get('strategy_type')} for explanation only."
    else:
        reason = "All option strategies are blocked."

    return {
        "ok": bool(selected),
        "selected_strategy": selected,
        "ranked_strategies": ranked,
        "paper_eligible_count": comparison.get("paper_eligible_count", 0),
        "research_only_count": comparison.get("research_only_count", 0),
        "blocked_count": comparison.get("blocked_count", 0),
        "selection_reason": reason,
        "warnings": comparison.get("warnings", []),
        "errors": comparison.get("errors", []),
    }

