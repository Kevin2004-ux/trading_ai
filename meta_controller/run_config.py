# meta_controller/run_config.py
from dataclasses import dataclass, field
from typing import List

@dataclass
class RunConfig:
    # --- Features & Data Labeling ---
    # The feature set for the simplified model used in optimization
    feature_list: List[str] = field(default_factory=lambda: ['sma_50', 'rsi', 'macd', 'relative_volume'])
    # The rule for creating the training data's "correct answers"
    profit_threshold: float = 0.02 
    
    # --- General Parameters ---
    history_years: int = 3
    future_days: int = 20
    epochs: int = 100
    learning_rate: float = 1e-3 # Default learning rate
    
    # --- Backtest Settings ---
    initial_capital: float = 100_000.0
    commission: float = 0.001