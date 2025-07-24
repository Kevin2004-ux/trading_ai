# tools/strategy_lookup.py
import sqlite3

def get_best_strategy_for_regime(regime_id: int) -> dict | None:
    """
    Queries the database for the best performing strategy for a given regime.
    """
    try:
        conn = sqlite3.connect('strategy_library.db')
        cursor = conn.cursor()
        
        cursor.execute("SELECT profit_target, stop_loss, backtest_return FROM strategies WHERE regime_id = ?", (regime_id,))
        result = cursor.fetchone()
        conn.close()
        
        if result:
            return {
                "profit_target": result[0],
                "stop_loss": result[1],
                "expected_return": result[2]
            }
        return None
    except Exception as e:
        print(f"Error querying strategy library: {e}")
        return None