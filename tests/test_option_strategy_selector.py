from options.strategy_selector import compare_option_strategies, select_best_option_strategy


def _strategy(strategy_type: str, status: str, score: float):
    return {
        "strategy_type": strategy_type,
        "status": status,
        "score": score,
        "evaluation": {
            "status": status,
            "score": score,
            "reasons": [],
            "warnings": [],
            "errors": [] if status != "blocked" else ["blocked"],
        },
        "max_loss": 2.0,
        "max_profit": 4.0,
    }


def test_selector_prefers_paper_eligible_strategy():
    result = select_best_option_strategy(
        [
            _strategy("long_call", "research_only", 90),
            _strategy("bull_call_debit_spread", "paper_eligible", 75),
        ]
    )

    assert result["ok"] is True
    assert result["selected_strategy"]["strategy_type"] == "bull_call_debit_spread"
    assert result["paper_eligible_count"] == 1


def test_selector_returns_best_research_only_if_no_paper_eligible_exists():
    result = select_best_option_strategy(
        [
            _strategy("covered_call_research", "research_only", 60),
            _strategy("cash_secured_put_research", "research_only", 72),
            _strategy("long_call", "blocked", 90),
        ]
    )

    assert result["selected_strategy"]["strategy_type"] == "cash_secured_put_research"
    assert "research-only" in result["selection_reason"]


def test_compare_option_strategies_counts_statuses():
    result = compare_option_strategies(
        [
            _strategy("long_call", "paper_eligible", 80),
            _strategy("covered_call_research", "research_only", 70),
            _strategy("long_put", "blocked", 10),
        ]
    )

    assert result["paper_eligible_count"] == 1
    assert result["research_only_count"] == 1
    assert result["blocked_count"] == 1

