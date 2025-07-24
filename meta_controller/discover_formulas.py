import sys
import os
import pandas as pd
import mlflow

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import config
# We'll use our existing PySR and data preparation logic
from retrain.distill_symbolic import find_symbolic_formula
from retrain.train_neural import prepare_training_data # This function is now more powerful!
from backtest import run_backtest_simulation

def validate_new_formula(formula_path: str) -> float:
    """
    Runs a backtest on a newly discovered formula to get its performance score.
    (This function remains a placeholder for now)
    """
    print(f"--- Validating new formula: {formula_path} ---")
    simulated_sharpe_ratio = 0.7 + (hash(formula_path) % 100) / 200.0
    print(f"  Validation complete. Simulated Sharpe Ratio: {simulated_sharpe_ratio:.2f}")
    return simulated_sharpe_ratio

def main():
    """
    The main script for the Symbolic Regression Meta-Controller.
    It now discovers formulas using technical, macro, sentiment, AND analyst data.
    """
    print("--- 🧠 Starting ADVANCED Formula Discovery and Validation ---")
    
    # 1. Prepare a rich dataset for discovery
    # THE ONLY CHANGE IS HERE. Our prepare_training_data function already
    # knows how to fetch and add the new features. We just need to call it.
    end_date = "2024-07-01"
    start_date = "2022-01-01"
    print(f"Preparing full dataset (including sentiment/ratings) from {start_date} to {end_date}...")
    Z_discovery, r_discovery = prepare_training_data(config.STOCKS_TO_MONITOR, start_date, end_date)

    if Z_discovery.empty:
        print("Could not generate a dataset for discovery. Exiting.")
        return

    y_target = r_discovery

    # 2. Run PySR to discover a new formula using ALL available data
    window_id = f"discovery_advanced_{pd.to_datetime('today').strftime('%Y-%m-%d')}"
    print(f"\n--- Running PySR to invent a new formula using {len(Z_discovery.columns)} features... ---")
    print(f"Available features: {list(Z_discovery.columns)}") # Log the features being used
    
    new_formula_code, _ = find_symbolic_formula(Z_discovery, y_target, window_id)
    new_formula_path = f"models/f_symb_{window_id}.py"

    # 3. Validate and Promote (logic remains the same)
    performance_score = validate_new_formula(new_formula_path)

    mlflow.set_experiment("Formula_Discovery_Advanced")
    with mlflow.start_run():
        print("\n--- Logging results to MLflow... ---")
        mlflow.log_param("formula_path", new_formula_path)
        mlflow.log_param("formula_code", new_formula_code)
        mlflow.log_param("features_used", list(Z_discovery.columns))
        mlflow.log_metric("sharpe_ratio", performance_score)

        baseline_performance = 1.0
        if performance_score > baseline_performance:
            mlflow.set_tag("status", "champion")
            print(f"🎉 New Champion Formula Found! Score: {performance_score:.2f}")
        else:
            mlflow.set_tag("status", "candidate")
            print(f"New candidate formula did not beat baseline. Score: {performance_score:.2f}")

if __name__ == "__main__":
    main()