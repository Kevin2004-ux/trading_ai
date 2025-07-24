# modeling/swing_policy.py

import torch
import torch.nn as nn
import torch.optim as optim
import pandas as pd
import numpy as np

class SwingTradePolicy(nn.Module):
    def __init__(self, feature_list: list, hidden_size: int = 64, output_size: int = 3):
        super(SwingTradePolicy, self).__init__()
        self.feature_list = feature_list
        self.network = nn.Sequential(
            nn.Linear(len(feature_list), hidden_size), nn.ReLU(), nn.Dropout(0.3),
            nn.Linear(hidden_size, hidden_size // 2), nn.ReLU(), nn.Dropout(0.3),
            nn.Linear(hidden_size // 2, output_size),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.network(x)

    def predict(self, feature_tensor: torch.Tensor) -> int:
        self.eval()
        with torch.no_grad():
            action_logits = self.forward(feature_tensor)
            action_probabilities = nn.functional.softmax(action_logits, dim=1)
        return torch.argmax(action_probabilities, dim=1).item()
        
    # --- CORRECTED LINE ---
    def train_model(self, training_df: pd.DataFrame, epochs: int = 100, learning_rate: float = 0.001, class_weights: torch.Tensor = None):
    # --- END CORRECTION ---
        print("\n--- 🧠 Starting Model Training ---")
        self.train()
        X = training_df[self.feature_list].values
        y = training_df['target'].values
        X_tensor, y_tensor = torch.from_numpy(X).float(), torch.from_numpy(y).long()
        
        # Pass the calculated class weights to the loss function
        loss_function = nn.CrossEntropyLoss(weight=class_weights)
        optimizer = optim.Adam(self.parameters(), lr=learning_rate)
        
        for epoch in range(epochs):
            outputs = self.forward(X_tensor)
            loss = loss_function(outputs, y_tensor)
            optimizer.zero_grad()
            loss.backward()
            optimizer.step()
            if (epoch + 1) % 10 == 0: print(f'Epoch [{epoch+1}/{epochs}], Loss: {loss.item():.4f}')
        print(f"--- ✅ Training Complete. ---")