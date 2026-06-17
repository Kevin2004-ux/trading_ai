from analytics.setup_decay import evaluate_all_setup_decay, evaluate_setup_decay


def _history(setup: str, outcomes: list[str]) -> list[dict]:
    return [
        {
            "ticker": f"T{i}",
            "setup_type": setup,
            "outcome": outcome,
            "risk_reward": 2.0,
            "holding_period_days": 7,
        }
        for i, outcome in enumerate(outcomes)
    ]


def test_setup_with_too_little_history_returns_watch():
    result = evaluate_setup_decay("breakout", _history("breakout", ["win", "loss"]))

    assert result["status"] == "watch"
    assert result["sample_size"] == 2


def test_setup_with_negative_expectancy_returns_decaying():
    history = _history("breakout", ["loss"] * 8 + ["win"] * 2)

    result = evaluate_setup_decay("breakout", history)

    assert result["status"] == "decaying"
    assert result["recent_expectancy_r"] < 0


def test_severely_bad_setup_returns_disabled():
    history = _history("breakout", ["loss"] * 15)

    result = evaluate_setup_decay("breakout", history)

    assert result["status"] == "disabled"
    assert result["recent_expectancy_r"] < -0.35


def test_evaluate_all_setup_decay_groups_by_setup():
    history = _history("breakout", ["loss"] * 15) + _history("pullback", ["win"] * 10)

    result = evaluate_all_setup_decay(history)

    assert result["ok"] is True
    assert result["setups"]["breakout"]["status"] == "disabled"
    assert result["setups"]["pullback"]["status"] == "healthy"
