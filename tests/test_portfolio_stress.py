from tracking.trade_logger import init_trade_tracking_db, log_recommendation
from simulation.portfolio_stress import estimate_portfolio_stress_loss, stress_test_open_paper_trades
from simulation.scenario_definitions import get_stress_scenario


def _trade(ticker="AAPL"):
    return {
        "ticker": ticker,
        "asset_type": "stock",
        "direction": "long",
        "entry_price": 100.0,
        "target_price": 112.0,
        "stop_loss": 94.0,
        "risk_reward": 2.0,
        "strategy": "swing",
        "setup_type": "momentum",
    }


def test_estimate_portfolio_stress_loss_calculates_risk_summary():
    scenario = get_stress_scenario("market_gap_down")["scenario"]
    result = estimate_portfolio_stress_loss([_trade(), _trade("MSFT")], scenario, config={"max_acceptable_loss_r": 3.0})

    assert result["ok"] is True
    assert result["open_trade_count"] == 2
    assert result["estimated_total_loss_r"] < 0
    assert result["worst_affected_trades"]


def test_stress_test_open_paper_trades_loads_from_temp_sqlite(tmp_path):
    db_path = str(tmp_path / "stress.db")
    init_trade_tracking_db(db_path)
    log_recommendation(**_trade(), db_path=db_path)

    result = stress_test_open_paper_trades(db_path, "market_gap_down")

    assert result["ok"] is True
    assert result["open_trade_count"] == 1
    assert result["scenario"]["scenario_name"] == "market_gap_down"


def test_stress_test_open_paper_trades_bad_scenario_is_clean_error(tmp_path):
    result = stress_test_open_paper_trades(str(tmp_path / "stress.db"), "missing")

    assert result["ok"] is False
    assert result["errors"]
