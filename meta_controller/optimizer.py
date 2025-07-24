# meta_controller/optimizer.py

import optuna
import pandas as pd
import sys
import time
sys.path.append('.')

from retrain.data_preparation import prepare_training_data
from modeling.swing_policy import SwingTradePolicy
from backtest import run_backtest
from meta_controller.run_config import RunConfig
    
def objective(trial: optuna.Trial):
    cfg = RunConfig()
    profit_target = trial.suggest_float("profit_target", 0.02, 0.15)
    stop_loss = trial.suggest_float("stop_loss", 0.01, 0.10)
    
    if stop_loss >= profit_target:
        raise optuna.exceptions.TrialPruned()

    print(f"\n--- Starting Trial {trial.number}: Target={profit_target:.2f}%, Stop={stop_loss:.2f}% ---")
    time.sleep(15)
    
    training_data = prepare_training_data("SPY", cfg)
    if training_data.empty:
        raise optuna.exceptions.TrialPruned()

    model = SwingTradePolicy(feature_list=cfg.feature_list)
    model.train_model(training_data, epochs=cfg.epochs, learning_rate=cfg.learning_rate)

    # --- CORRECTED LINE ---
    # Pass the profit_target and stop_loss from the trial to the backtester
    total_return = run_backtest(training_data, model, cfg, profit_target_t=profit_target, stop_loss_s=stop_loss)
    # --- END CORRECTION ---
    
    return total_return
    
if __name__ == "__main__":
    study = optuna.create_study(direction="maximize")
    print("--- 🚀 Starting Quantitative Strategy Optimization with Optuna ---")
    study.optimize(objective, n_trials=20)
    print("\n--- ✅ Optimization Complete ---")
    print(f"Best trial found:")
    print(f"  Return: {study.best_value:.2f}%")
    print(f"  Best Parameters: {study.best_params}")