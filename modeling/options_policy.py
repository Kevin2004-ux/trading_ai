# modeling/options_policy.py

import torch
import torch.nn as nn
import torch.optim as optim
import pandas as pd
from datetime import datetime, timedelta

# Add sys path to import from other folders
import sys
sys.path.append('.')

from retrain.options_data_preparation import prepare_options_training_data

class OptionsDecisionPolicy(nn.Module):
    """
    A neural network policy for scoring the attractiveness of an individual
    options contract based on its features.
    """
    def __init__(self, input_features: int = 7, hidden_size: int = 64):
        """
        Initializes the model layers.
        - input_features: The number of option-specific features.
        """
        super(OptionsDecisionPolicy, self).__init__()
        
        self.feature_list = [
            'time_to_expiration_days', 'moneyness', 'delta', 'gamma', 
            'theta', 'vega', 'implied_volatility'
        ]
        
        self.network = nn.Sequential(
            nn.Linear(input_features, hidden_size),
            nn.ReLU(),
            nn.Dropout(0.2),
            nn.Linear(hidden_size, hidden_size // 2),
            nn.ReLU(),
            # The output is a single score for the contract
            nn.Linear(hidden_size // 2, 1)
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """Defines the forward pass of the model."""
        return self.network(x)

    def score_contracts(self, options_features_df: pd.DataFrame) -> pd.DataFrame:
        """
        Takes a DataFrame of option features and returns a score for each contract.
        """
        self.eval()
        if options_features_df.empty:
            return pd.DataFrame()

        features_to_score = options_features_df[self.feature_list].values
        features_tensor = torch.from_numpy(features_to_score).float()

        with torch.no_grad():
            scores = self.forward(features_tensor)

        options_features_df['score'] = scores.numpy()
        return options_features_df

    def train_model(self, training_df: pd.DataFrame, epochs: int = 100):
        """
        Trains the neural network using the prepared labeled options data.
        """
        print("\n--- 🧠 Starting Options Model Training ---")
        self.train()
        
        X = training_df[self.feature_list].values
        y = training_df['target_score'].values
        X_tensor = torch.from_numpy(X).float()
        # --- CORRECTED LINE ---
        y_tensor = torch.from_numpy(y).float().view(-1, 1)
        # --- END CORRECTION ---

        loss_function = nn.MSELoss()
        optimizer = optim.Adam(self.parameters(), lr=0.001)

        for epoch in range(epochs):
            outputs = self.forward(X_tensor)
            loss = loss_function(outputs, y_tensor)
            
            optimizer.zero_grad()
            loss.backward()
            optimizer.step()

            if (epoch + 1) % 10 == 0:
                print(f'Epoch [{epoch+1}/{epochs}], Loss: {loss.item():.4f}')
        
        model_path = "options_decision_model.pth"
        torch.save(self.state_dict(), model_path)
        print(f"--- ✅ Training Complete. Model saved to {model_path} ---")

# This allows us to run this file directly to train the model
if __name__ == "__main__":
    historical_date = datetime.now() - timedelta(days=30)
    while historical_date.weekday() >= 5:
        historical_date -= timedelta(days=1)

    labeled_data = prepare_options_training_data("SPY", historical_date)
    
    if not labeled_data.empty:
        # Create a model instance
        model = OptionsDecisionPolicy()
        # Train the model
        model.train_model(labeled_data)