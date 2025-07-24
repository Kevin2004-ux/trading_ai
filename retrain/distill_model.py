# retrain/distill_model.py

import pandas as pd
import torch
from pysr import PySRRegressor
import sympy

import sys
sys.path.append('.')

from modeling.swing_policy import SwingTradePolicy

def find_symbolic_formula():
    """
    Loads a trained neural network and uses PySR to find a simple
    mathematical formula that approximates its decisions.
    """
    print("--- 🧠 Starting Model Distillation with PySR ---")
    
    # 1. Load the enriched data the model was trained on
    try:
        enriched_data = pd.read_parquet("swing_training_data_final.parquet")
        print("Enriched data loaded successfully.")
    except FileNotFoundError:
        print("Error: `swing_training_data_final.parquet` not found.")
        return

    # 2. Load our trained PyTorch model
    model = SwingTradePolicy()
    model.load_state_dict(torch.load("swing_trade_model_v4.pth"))
    model.eval()
    print("Trained v4 model loaded successfully.")

    # 3. Get the neural network's predictions (the "answers" for PySR)
    features_df = enriched_data[model.feature_list]
    X_tensor = torch.from_numpy(features_df.values).float()
    
    with torch.no_grad():
        y_target = model(X_tensor).numpy()

    # 4. Initialize and run the Symbolic Regressor
    pysr_model = PySRRegressor(
        niterations=10,
        binary_operators=["+", "-", "*", "/"],
        unary_operators=["inv(x) = 1/x"],
        # --- ADD THIS LINE ---
        extra_sympy_mappings={"inv": lambda x: 1/x},
        model_selection="best",
    )

    print("\n--- Fitting PySR model to find formula... This will take a few minutes. ---")
    pysr_model.fit(features_df, y_target[:, 2]) # Targeting the "BUY" logit

    print("\n--- ✅ Distillation Complete ---")
    print("Best formula found that approximates the 'BUY' signal:")
    print(pysr_model)


if __name__ == "__main__":
    find_symbolic_formula()