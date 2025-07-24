# backtest.py
import pandas as pd
import torch
from tqdm import tqdm
import sys
sys.path.append('.')

from modeling.swing_policy import SwingTradePolicy
from meta_controller.run_config import RunConfig

def run_backtest(
    historical_data: pd.DataFrame, 
    model: SwingTradePolicy, 
    cfg: RunConfig,
    profit_target_t: float,
    stop_loss_s: float
) -> float:
    
    print("\n--- 🏁 Starting Swing Trade Backtest Simulation ---")
    cash, shares = cfg.initial_capital, 0.0
    portfolio_values = [cfg.initial_capital]
    entry_price, buys, sells = None, 0, 0
    
    features_to_use = model.feature_list

    for i in tqdm(range(1, len(historical_data)), desc="Simulating Trades"):
        current_price = historical_data.iloc[i]['close']
        feats = historical_data.iloc[i][features_to_use].values
        decision = model.predict(torch.tensor(feats).float().unsqueeze(0))

        # --- REVISED LOGIC ---
        # If we are flat (shares == 0), look for a BUY signal to enter.
        if shares == 0:
            if decision == 2: # BUY Signal
                buys += 1
                shares_to_buy = (cash * 0.95) / current_price # Use 95% of cash
                shares = shares_to_buy
                cash -= shares * current_price
                entry_price = current_price
        
        # If we have a position (shares > 0), look for a reason to exit.
        elif shares > 0:
            profit_target_price = entry_price * (1 + profit_target_t)
            stop_loss_price = entry_price * (1 - stop_loss_s)
            
            # Exit conditions: explicit SELL signal, hit profit target, or hit stop-loss
            if decision == 0 or current_price >= profit_target_price or current_price <= stop_loss_price:
                sells += 1
                cash += shares * current_price * (1 - cfg.commission)
                shares, entry_price = 0.0, None
        # --- END REVISED LOGIC ---

        portfolio_values.append(cash + (shares * current_price))
        
    final_value = portfolio_values[-1]
    total_return = (final_value - cfg.initial_capital) / cfg.initial_capital * 100
    
    print(f"--- ✅ Backtest Complete ---")
    print(f"Total Buys: {buys}, Total Sells: {sells}")
    print(f"Final Portfolio Value: ${final_value:,.2f}, Return: {total_return:.2f}%")
    return total_return