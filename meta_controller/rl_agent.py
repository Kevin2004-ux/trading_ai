import sys
import os
import pandas as pd
import numpy as np
from stable_baselines3 import PPO
from stable_baselines3.common.vec_env import DummyVecEnv
from stable_baselines3.common.env_checker import check_env

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from meta_controller.rl_environment import TradingEnv
from retrain.train_neural import prepare_training_data
from discovery_pipeline import fetch_polygon_data
import config

def main():
    # ... (Data preparation and training code is the same)
    print("--- 🤖 Starting RL Agent Training ---")
    print("Preparing data for RL environment...")
    ticker_for_training = config.STOCKS_TO_MONITOR[0]
    end_date = "2024-07-01"
    start_date = "2022-01-01"
    features_df, _ = prepare_training_data([ticker_for_training], start_date, end_date)
    prices_df = fetch_polygon_data(ticker_for_training, start_date, end_date)
    if features_df.empty or prices_df is None:
        print("Could not generate data. Exiting.")
        return
    common_index = features_df.index.intersection(prices_df.index)
    features_df = features_df.loc[common_index]
    prices_df = prices_df.loc[common_index]
    env = TradingEnv(features_df, prices_df, render_mode="human")
    check_env(env)
    vec_env = DummyVecEnv([lambda: env])
    print("\n--- Training the agent... This may take a few minutes. ---")
    model = PPO("MlpPolicy", vec_env, verbose=1)
    model.learn(total_timesteps=20000)
    model.save("models/rl_trader_agent")
    print("--- ✅ Training Complete. Model saved to models/rl_trader_agent ---")

    print("\n--- Evaluating trained agent's performance... ---")
    obs = vec_env.reset()
    for i in range(len(features_df) - 1):
        action, _states = model.predict(obs, deterministic=True)
        obs, rewards, done, info = vec_env.step(action)
        
        # --- ADD THIS LINE BACK ---
        vec_env.render() # Explicitly call render in the evaluation loop
        
        if done:
            break

if __name__ == "__main__":
    main()