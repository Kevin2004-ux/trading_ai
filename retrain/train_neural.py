# retrain/train_champion.py

import hydra
from omegaconf import DictConfig
import torch
import sys
sys.path.append('.')

from retrain.data_preparation import prepare_training_data
from modeling.swing_policy import SwingTradePolicy

@hydra.main(config_path="../configs", config_name="champion_config", version_base=None)
def train_champion_model(cfg: DictConfig):
    """
    Loads the champion configuration and trains the final production model.
    """
    print("--- 🏆 Training Champion Model with Optimal Configuration ---")
    
    # 1. Prepare the data using the optimal profit threshold
    training_data = prepare_training_data("SPY", cfg)
    
    if training_data.empty:
        print("❌ Could not prepare data. Aborting.")
        return

    # 2. Initialize the model with the champion feature list
    model = SwingTradePolicy(feature_list=cfg.feature_list)
    
    # 3. Train the model with the optimal learning rate and more epochs
    model.train_model(
        training_data, 
        epochs=cfg.epochs, 
        learning_rate=cfg.learning_rate
    )

    # 4. Save the final model with a clear name
    final_model_path = "champion_model.pth"
    torch.save(model.state_dict(), final_model_path)
    print(f"\n--- ✅ Champion model saved to {final_model_path} ---")

if __name__ == "__main__":
    train_champion_model()