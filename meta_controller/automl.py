import optuna
import mlflow
import sys
import os
import pandas as pd

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from backtest import run_backtest_simulation

def objective(trial: optuna.Trial) -> float:
    params = {
        'start_date': "2024-01-01",
        'end_date': "2024-07-01",
        'simulated_win_rate': trial.suggest_float('simulated_win_rate', 0.45, 0.65),
        'risk_level': trial.suggest_categorical('risk_level', ['low', 'medium', 'high'])
    }

    with mlflow.start_run():
        mlflow.log_params(params)

        # --- CATCH THE NEW TRADE LOG ---
        # The backtester now returns two items
        final_portfolio_value, trades_df = run_backtest_simulation(params)

        mlflow.log_metric("final_portfolio_value", final_portfolio_value)

        # --- SAVE THE LOG AS A FILE (ARTIFACT) ---
        if not trades_df.empty:
            # Create a temporary file path to save the log
            log_file_path = "temp_trade_log.csv"
            trades_df.to_csv(log_file_path, index=False)
            
            # Tell MLflow to log this file as an artifact for this trial
            mlflow.log_artifact(log_file_path, "trade_logs")
            
            # Clean up the temporary file
            os.remove(log_file_path)

    return final_portfolio_value

if __name__ == "__main__":
    mlflow.set_experiment("Trading_Strategy_Optimization_with_Logs")

    study = optuna.create_study(direction="maximize")
    study.optimize(objective, n_trials=10) # Reduced trials for a quick test

    print("\n--- ✅ AutoML Study Complete ---")
    print("Best trial:")
    trial = study.best_trial
    print(f"  Value (Final Portfolio): ${trial.value:,.2f}")
    print("  Params: ", trial.params)
    print("\nTo see the detailed trade logs, run 'mlflow ui' and check the 'Artifacts' section of the best run.")