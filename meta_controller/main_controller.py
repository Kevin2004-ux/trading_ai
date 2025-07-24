# meta_controller/main_controller.py
import optuna
import pandas as pd
import sqlite3
import sys
from datetime import datetime
sys.path.append('.')

from retrain.data_preparation import prepare_training_data
from modeling.swing_policy import SwingTradePolicy
from backtest import run_backtest
from meta_controller.run_config import RunConfig

def run_optimization_for_regime(regime_data: pd.DataFrame, cfg: RunConfig):
    def objective(trial: optuna.Trial):
        profit_target = trial.suggest_float("profit_target", 0.02, 0.20)
        stop_loss = trial.suggest_float("stop_loss", 0.01, 0.10)
        if stop_loss >= profit_target: raise optuna.exceptions.TrialPruned()
        
        model = SwingTradePolicy(feature_list=cfg.feature_list)
        model.train_model(regime_data)
        
        total_return = run_backtest(regime_data, model, cfg, profit_target, stop_loss)
        return total_return

    study = optuna.create_study(direction="maximize")
    study.optimize(objective, n_trials=30)
    return study.best_params, study.best_value

if __name__ == "__main__":
    print("--- 🚀 Starting Regime-Aware Meta-Controller ---")
    cfg = RunConfig()
    full_training_data = prepare_training_data("SPY", cfg)

    conn = sqlite3.connect('strategy_library.db')
    
    if 'regime' in full_training_data.columns:
        for regime_id in sorted(full_training_data['regime'].unique()):
            print(f"\n{'='*50}\nOptimizing for Market Regime: {regime_id}\n{'='*50}")
            
            regime_data = full_training_data[full_training_data['regime'] == regime_id].copy()
            if len(regime_data) < 50:
                print(f"Skipping Regime {regime_id} due to insufficient data.")
                continue
                
            best_params, best_return = run_optimization_for_regime(regime_data, cfg)
            
            print(f"\n--- ✅ Best Strategy for Regime {regime_id} ---")
            print(f"  Return: {best_return:.2f}%")
            print(f"  Parameters: {best_params}")
            
            # Save the winning strategy to the database
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO strategies (regime_id, profit_target, stop_loss, backtest_return, last_updated)
                VALUES (?, ?, ?, ?, ?)
            """, (
                int(regime_id),
                best_params['profit_target'],
                best_params['stop_loss'],
                best_return,
                datetime.now().isoformat()
            ))
            conn.commit()
            print("--- 💾 Strategy Library Database Updated ---")

    conn.close()
    print("\n\n--- 🏆 Full Regime-Aware Optimization Complete ---")