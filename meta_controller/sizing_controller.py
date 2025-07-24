# meta_controller/sizing_controller.py
    
import optuna
import mlflow  # Import mlflow
import sys
import time
sys.path.append('.')
    
from retrain.data_preparation import prepare_training_data
from modeling.swing_policy import SwingTradePolicy
from backtest import run_backtest
from meta_controller.run_config import RunConfig
    
# --- Setup for the Strategy Library (MLflow) ---
# This sets the name of our "lab notebook"
mlflow.set_experiment("Swing Trading Strategy Optimization")

# (The data prep and model training from before remains the same)
cfg = RunConfig(profit_threshold=0.01359)
TRAINING_DATA = prepare_training_data("SPY", cfg)
SIGNAL_MODEL = SwingTradePolicy(feature_list=cfg.feature_list)
SIGNAL_MODEL.train_model(TRAINING_DATA)
    
def objective(trial: optuna.Trial):
    # Start a new "page" in our lab notebook for this experiment
    with mlflow.start_run():
        
        profit_target = trial.suggest_float("profit_target", 0.02, 0.20)
        stop_loss = trial.suggest_float("stop_loss", 0.01, 0.10)
        
        if stop_loss >= profit_target:
            raise optuna.exceptions.TrialPruned()
    
        print(f"\n--- Testing Strategy: Target={profit_target:.2%}, Stop={stop_loss:.2%} ---")
        
        # --- Log the parameters we are testing ---
        mlflow.log_param("profit_target", profit_target)
        mlflow.log_param("stop_loss", stop_loss)

        total_return = run_backtest(
            historical_data=TRAINING_DATA, 
            model=SIGNAL_MODEL, 
            cfg=cfg, 
            profit_target_t=profit_target, 
            stop_loss_s=stop_loss
        )
        
        # --- Log the final result of the experiment ---
        mlflow.log_metric("final_return_pct", total_return)
        
        return total_return
        
if __name__ == "__main__":
    study = optuna.create_study(direction="maximize")
    print("\n--- 🚀 Starting Position Sizing Optimization ---")
    study.optimize(objective, n_trials=50)
    
    print("\n--- ✅ Optimization Complete ---")
    print("Best risk management strategy found:")
    print(f"  Return: {study.best_value:.2f}%")
    print(f"  Best Parameters: {study.best_params}")