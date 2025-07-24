# meta_controller/entry_controller.py

import optuna
import sys
import time
sys.path.append('.')

from retrain.data_preparation import prepare_training_data
from modeling.swing_policy import SwingTradePolicy
from meta_controller.signal_validator import validate_signals # Import our new validator
from meta_controller.run_config import RunConfig
    
def objective(trial: optuna.Trial):
    cfg = RunConfig()
    cfg.profit_threshold = trial.suggest_float("profit_threshold", 0.01, 0.10)
    cfg.learning_rate = trial.suggest_float("learning_rate", 1e-4, 1e-2, log=True)
    
    print(f"\n--- Starting Trial {trial.number}: profit_threshold={cfg.profit_threshold:.4f} ---")
    time.sleep(15)

    training_data = prepare_training_data("SPY", cfg)
    if training_data.empty:
        raise optuna.exceptions.TrialPruned()

    model = SwingTradePolicy(feature_list=cfg.feature_list)
    model.train_model(training_data, epochs=cfg.epochs, learning_rate=cfg.learning_rate)

    # Use the new signal validator to get the win rate
    win_rate = validate_signals(training_data, model, cfg)
    
    # Optuna will now try to maximize this win_rate
    return win_rate
    
if __name__ == "__main__":
    study = optuna.create_study(direction="maximize")
    print("--- 🚀 Starting Entry Logic Optimization ---")
    study.optimize(objective, n_trials=20)
    print("\n--- ✅ Optimization Complete ---")
    print(f"Best trial found:")
    print(f"  Win Rate: {study.best_value:.2f}%")
    print(f"  Best Parameters: {study.best_params}")