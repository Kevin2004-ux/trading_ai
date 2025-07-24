import pandas as pd
import numpy as np
import torch
from pysr import PySRRegressor
import os
import sys
import sympy

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import config
from retrain.train_neural import MLP

def generate_neural_predictions(Z, window_id):
    """Loads the correctly versioned neural network to generate predictions."""
    print("Loading trained neural network to generate predictions...")
    
    # --- THIS IS THE FIX ---
    # Construct the full, correct path to the versioned model
    model_path = f"models/neural_model_{window_id}.ckpt"
    
    if not os.path.exists(model_path):
        print(f"Error: Model file not found at {model_path}")
        # Return empty array if model doesn't exist for this window
        return np.array([]) 
    
    input_size = Z.shape[1]
    model = MLP(input_size)
    model.load_state_dict(torch.load(model_path)) # Now loads the correct path
    model.eval()
    
    with torch.no_grad():
        X_tensor = torch.from_numpy(Z.values).float()
        predictions = model(X_tensor)
        
    return predictions.numpy().flatten()

def find_symbolic_formula(Z, y_neural, window_id):
    """Finds a symbolic formula and saves it with a versioned name."""
    print("\nStarting symbolic regression with PySR...")
    
    model = PySRRegressor(
        niterations=config.PYSR_ITERATIONS,
        binary_operators=["+", "-", "*", "/"],
        unary_operators=["exp", "sin", "cos", "log1p"],
        model_selection="best",
        procs=0, # Use all available processors
    )
    model.fit(Z, y_neural)

    print("\nSymbolic regression complete.")
    print(f"Best formula found: {model}")

    sympy_formula = model.sympy()
    feature_names = model.feature_names_in_
    python_code_str = sympy.pycode(sympy_formula)
    
    for i, name in enumerate(feature_names):
        python_code_str = python_code_str.replace(name, f"z[{i}]")

    file_content = f"""import numpy as np

def f_symb(z):
    # Features: {feature_names}
    return {python_code_str}
"""
    # Save the formula with a versioned name
    formula_path = f"models/f_symb_{window_id}.py"
    with open(formula_path, "w") as f:
        f.write(file_content)
    print(f"Formula exported as a Python function to {formula_path}")
    
    # Return the code and formula for use in other parts of the pipeline
    return file_content, str(sympy_formula)