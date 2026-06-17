from risk.circuit_breaker import evaluate_drawdown_circuit_breaker


def _trades(outcomes: list[str], setup_type: str = "momentum_breakout") -> list[dict]:
    return [
        {
            "ticker": f"T{i}",
            "setup_type": setup_type,
            "outcome": outcome,
            "risk_reward": 2.0,
            "realized_return": 2.0 if outcome == "win" else -1.0 if outcome == "loss" else 0.0,
        }
        for i, outcome in enumerate(outcomes)
    ]


def test_normal_trade_history_allows_new_trades():
    result = evaluate_drawdown_circuit_breaker(_trades(["win", "loss", "win", "win"]))

    assert result["circuit_status"] == "normal"
    assert result["new_trades_allowed"] is True
    assert result["max_allowed_risk_multiplier"] == 1.0


def test_three_loss_streak_produces_caution():
    result = evaluate_drawdown_circuit_breaker(_trades(["win", "loss", "loss", "loss"]))

    assert result["circuit_status"] == "caution"
    assert result["new_trades_allowed"] is True


def test_five_loss_streak_produces_reduced_risk():
    result = evaluate_drawdown_circuit_breaker(_trades(["win", "loss", "loss", "loss", "loss", "loss"]))

    assert result["circuit_status"] == "reduced_risk"
    assert result["max_allowed_risk_multiplier"] == 0.5


def test_seven_loss_streak_blocks_new_trades():
    result = evaluate_drawdown_circuit_breaker(_trades(["loss"] * 7))

    assert result["circuit_status"] == "blocked"
    assert result["new_trades_allowed"] is False
    assert result["max_allowed_risk_multiplier"] == 0.0


def test_negative_expectancy_triggers_reduced_risk():
    result = evaluate_drawdown_circuit_breaker(_trades(["loss"] * 19 + ["win"]))

    assert result["circuit_status"] in {"reduced_risk", "blocked"}
    assert result["recent_expectancy_r"] < -0.25

