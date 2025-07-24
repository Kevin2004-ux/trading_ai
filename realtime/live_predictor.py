import os
import sys
import numpy as np
import json

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from realtime.features import get_latest_feature_vector
from realtime.forecast import get_ensemble_forecast
from realtime.market_impact_model import adjust_with_market_impact
from realtime.options_eval import evaluate_options
from realtime.risk_manager import apply_risk_management, get_sector

# In a real app, this would be loaded from a database or a file
PORTFOLIO_STATE = {
    'total_value': 100000.0, 'cash': 100000.0,
    'positions': {}, 'sector_exposure': {}
}

def predict(ticker, aggressiveness="balanced"):
    """
    Runs the full real-time prediction pipeline and now returns a
    rich dictionary with all the data needed for a full explanation.
    """
    # 1. Get Features
    z0, latest_data = get_latest_feature_vector(ticker)
    if z0 is None:
        return {"error": "Could not build feature vector."}

    latest_data['ticker'] = ticker

    # 2. Get Forecast
    model_config = {} # Placeholder for loading a specific model config
    window_id = model_config.get('window_id')
    ŷ_raw = get_ensemble_forecast(z0, window_id)
    
    # 3. Adjust Forecast
    k_learned = model_config.get('optimal_k', 0.1)
    R_adj = adjust_with_market_impact(ŷ_raw, latest_data.get('Relative_Volume', 1.0), k_learned)

    # 4. Evaluate Options
    S0 = latest_data['Close']
    sigma_imp = latest_data['ATR'] / S0 / np.sqrt(252)
    top_options = evaluate_options(S0, R_adj, sigma_imp, aggressiveness=aggressiveness)
    
    # 5. Apply Risk Management
    sized_options = apply_risk_management(top_options, latest_data, PORTFOLIO_STATE, aggressiveness=aggressiveness)
    
    # 6. --- NEW: Build the Rich Dossier ---
    # We now package all the important data points for the Translator
    prediction_dossier = {
        "ticker": ticker,
        "final_forecast_pct": round(R_adj * 100, 2),
        "raw_forecast": round(ŷ_raw, 4),
        "aggressiveness_profile": aggressiveness,
        "key_drivers": {
            "news_sentiment": round(latest_data.get('news_sentiment', 0.0), 2),
            "analyst_rating_momentum": int(latest_data.get('analyst_rating_momentum', 0)),
            "market_regime": "Bullish" if latest_data.get('regime', 0) == 1 else "Bearish",
            "relative_volume": round(latest_data.get('Relative_Volume', 1.0), 2)
        },
        "recommended_strategy": sized_options[0] if sized_options else "None"
    }
    return prediction_dossier

# Example usage
if __name__ == "__main__":
    import config
    ticker_to_test = config.STOCKS_TO_MONITOR[0]
    final_dossier = predict(ticker_to_test, aggressiveness="aggressive")
    print(json.dumps(final_dossier, indent=2))