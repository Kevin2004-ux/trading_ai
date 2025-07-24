import json
import torch
import numpy as np
import os
import sys
import importlib.util

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from retrain.train_neural import MLP

def load_func_from_file(filepath, func_name):
    """Dynamically loads a function from a Python file."""
    if not os.path.exists(filepath):
        print(f"Warning: Could not find model file: {filepath}")
        return None
    spec = importlib.util.spec_from_file_location(func_name, filepath)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return getattr(module, func_name)

def get_latest_model_window_id():
    """Finds the most recent model window ID from saved config files."""
    if not os.path.exists('models'): return None
    configs = [f for f in os.listdir('models') if f.startswith('model_config_')]
    if not configs: return None
    # Sort descending and get the date part of the filename
    latest_config = sorted(configs, reverse=True)[0]
    return latest_config.split('_')[2].replace('.json','')

def get_ensemble_forecast(feature_vector, window_id=None):
    """
    Calculates the ensemble forecast. It can now load a specific version
    of the models using a window_id.
    """
    try:
        # If no specific version is requested, use the latest one available
        if window_id is None:
            window_id = get_latest_model_window_id()
            if window_id is None:
                raise FileNotFoundError("No trained models found.")

        # --- THIS IS THE NEW LOGIC ---
        # Construct file paths based on the window_id
        config_path = f"models/model_config_{window_id}.json"
        neural_model_path = f"models/neural_model_{window_id}.ckpt"
        symb_model_path = f"models/f_symb_{window_id}.py"

        with open(config_path, 'r') as f:
            model_config = json.load(f)

        # For this prototype, we'll use placeholder weights. A full system would
        # calculate and save these during walk-forward training.
        WEIGHTS = {"neural": 0.5, "symb": 0.5}

        # Load the versioned neural network
        # Note: The input size should match what was used during training for this window
        input_size = len(model_config.get('base_features', [])) + len(model_config.get('selected_features', []))
        neural_model = MLP(input_size)
        neural_model.load_state_dict(torch.load(neural_model_path))
        neural_model.eval()
        
        # Load the versioned symbolic function
        f_symb = load_func_from_file(symb_model_path, "f_symb")
        if f_symb is None: raise FileNotFoundError(f"Symbolic model not found for window {window_id}")

        MODELS_LOADED = True
    except Exception as e:
        print(f"Warning: Could not load all models for window '{window_id}': {e}. Forecast will be neutral (0.0).")
        MODELS_LOADED = False

    if not MODELS_LOADED or feature_vector is None:
        return 0.0
        
    z0 = np.array(feature_vector)
    
    # Generate predictions from each model
    with torch.no_grad():
        X_tensor = torch.from_numpy(z0).float()
        ŷ_n = neural_model(X_tensor).item()
        
    ŷ_s = f_symb(z0)

    # Combine using weights
    ŷ_raw = WEIGHTS['neural'] * ŷ_n + WEIGHTS['symb'] * ŷ_s
    
    # print(f"  Ensemble forecast -> Neural: {ŷ_n:.4f}, Symbolic: {ŷ_s:.4f}")
    # print(f"  Final raw forecast (ŷ_raw): {ŷ_raw:.4f}")
    return ŷ_raw