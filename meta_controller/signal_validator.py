# meta_controller/signal_validator.py

import pandas as pd
import torch
from tqdm import tqdm
import sys
sys.path.append('.')

from modeling.swing_policy import SwingTradePolicy
from meta_controller.run_config import RunConfig

def validate_signals(historical_data: pd.DataFrame, model: SwingTradePolicy, cfg: RunConfig) -> float:
    """
    Performs a simple walk-forward validation of BUY/SELL signals.
    Returns the 'win rate' of the signals.
    """
    print("\n--- 🔬 Validating Signal Accuracy ---")
    
    features_to_use = model.feature_list
    wins = 0
    trades = 0

    for i in tqdm(range(1, len(historical_data) - cfg.future_days), desc="Validating Signals"):
        current_features = historical_data.iloc[i][features_to_use].values
        feature_tensor = torch.tensor(current_features).float().unsqueeze(0)
        
        decision = model.predict(feature_tensor)

        if decision == 2 or decision == 0: # If we get a BUY or SELL signal
            trades += 1
            actual_outcome = historical_data.iloc[i]['target']
            
            if decision == actual_outcome:
                wins += 1 # The model's prediction matched the future reality
    
    win_rate = (wins / trades) * 100 if trades > 0 else 0.0
    
    print(f"--- ✅ Validation Complete ---")
    print(f"Total Signals: {trades}, Wins: {wins}, Win Rate: {win_rate:.2f}%")
    return win_rate