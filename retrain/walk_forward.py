import json
import numpy as np
import pandas as pd
import torch
import os
import sys
from datetime import datetime
from dateutil.relativedelta import relativedelta
from sklearn.linear_model import LassoCV
from sklearn.preprocessing import StandardScaler

# Add parent directory to path to import other project modules
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import config
from retrain.train_neural import prepare_training_data, train_model, MLP, BASE_FEATURE_NAMES
from retrain.distill_symbolic import generate_neural_predictions, find_symbolic_formula
from retrain.generate_feature_hypotheses import generate_hypotheses
from realtime.market_impact_model import adjust_with_market_impact

def select_best_features(hypotheses, Z_val, r_val):
    """Uses Lasso regression to select the most valuable new features from LLM suggestions."""
    if not hypotheses:
        return []

    print("--- Selecting best features from LLM hypotheses using LassoCV ---")
    X_hypo_val = pd.DataFrame(index=Z_val.index)
    for name, code in hypotheses.items():
        try:
            X_hypo_val[name] = Z_val.apply(lambda row: eval(code, {"np": np, "z": row.values}), axis=1)
        except Exception as e:
            print(f"  Warning: Could not evaluate hypothesis '{name}': {e}")

    X_hypo_val.replace([np.inf, -np.inf], np.nan, inplace=True)
    X_hypo_val.fillna(0, inplace=True)

    if X_hypo_val.empty:
        return []

    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X_hypo_val)

    lasso = LassoCV(cv=5, random_state=42, max_iter=2000).fit(X_scaled, r_val)
    selected_indices = np.where(lasso.coef_ != 0)[0]
    selected_features = X_hypo_val.columns[selected_indices].tolist()
    
    print(f"Lasso selected {len(selected_features)} features: {selected_features}")
    return selected_features

def optimize_impact_parameter(ŷ_val, Z_val, r_val):
    """Finds the optimal 'k' for the market impact model on the validation set."""
    print("--- Optimizing market impact parameter 'k' ---")
    best_k = 0
    best_mse = np.mean((ŷ_val - r_val) ** 2)

    # The 'Relative_Volume' is the 2nd feature (index 1) in BASE_FEATURE_NAMES
    relative_volumes = Z_val.iloc[:, 1].values
    
    for k in np.arange(0, 0.55, 0.05):
        r_adj = adjust_with_market_impact(ŷ_val, relative_volumes, k)
        mse = np.mean((r_adj - r_val) ** 2)
        
        if mse < best_mse:
            best_mse = mse
            best_k = k
            
    print(f"Optimal 'k' found: {best_k:.2f} (MSE: {best_mse:.6f})")
    return best_k

def main():
    print("Starting walk-forward analysis with hypothesis testing and optimization...")
    # The blue sundial tells us the current time, which we use as the end date
    end_date = datetime.now()
    
    # Calculate the total timeframe needed for the first window
    total_initial_months = (config.TRAIN_YEARS * 12) + config.VALIDATION_MONTHS
    start_date = end_date - relativedelta(months=total_initial_months)
    
    current_window_start = start_date

    while current_window_start + relativedelta(years=config.TRAIN_YEARS, months=config.VALIDATION_MONTHS) <= end_date:
        train_start = current_window_start
        train_end = train_start + relativedelta(years=config.TRAIN_YEARS)
        val_start = train_end
        
        # --- THIS IS THE UPDATED LINE ---
        val_end = val_start + relativedelta(months=config.VALIDATION_MONTHS)
        
        window_id = train_start.strftime('%Y-%m-%d')
        print(f"\n{'='*60}\nProcessing Window: {window_id}\n{'='*60}")
        print(f"  TRAIN: {train_start.date()} to {train_end.date()}")
        print(f"  VALIDATE: {val_start.date()} to {val_end.date()}")
        
        Z_train, r_train = prepare_training_data(config.STOCKS_TO_MONITOR, train_start.strftime('%Y-%m-%d'), train_end.strftime('%Y-%m-%d'))
        if Z_train.empty:
            current_window_start += relativedelta(months=config.ROLLING_WINDOW_STEP_MONTHS)
            continue
            
        train_model(Z_train, r_train, window_id)
        ŷ_neural_train = generate_neural_predictions(Z_train, window_id)
        symbolic_code, symbolic_formula = find_symbolic_formula(Z_train, ŷ_neural_train, window_id)

        hypotheses = generate_hypotheses(list(Z_train.columns), symbolic_formula)

        Z_val, r_val = prepare_training_data(config.STOCKS_TO_MONITOR, val_start.strftime('%Y-%m-%d'), val_end.strftime('%Y-%m-%d'))
        if Z_val.empty:
            current_window_start += relativedelta(months=config.ROLLING_WINDOW_STEP_MONTHS)
            continue

        selected_features = select_best_features(hypotheses, Z_val, r_val)
        
        ŷ_neural_val = generate_neural_predictions(Z_val, window_id)
        optimal_k = optimize_impact_parameter(ŷ_neural_val, Z_val, r_val)
        
        model_config = {
            "window_id": window_id,
            "optimal_k": optimal_k,
            "llm_hypotheses": hypotheses,
            "selected_features": selected_features,
            "base_features": BASE_FEATURE_NAMES,
        }
        
        config_path = f"models/model_config_{window_id}.json"
        with open(config_path, 'w') as f:
            json.dump(model_config, f, indent=2)
        print(f"Full model configuration saved to {config_path}")

        current_window_start += relativedelta(months=config.ROLLING_WINDOW_STEP_MONTHS)

    print("\nFull walk-forward model training and optimization complete.")

if __name__ == "__main__":
    main()