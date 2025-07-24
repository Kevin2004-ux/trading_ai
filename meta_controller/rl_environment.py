import gymnasium as gym
from gymnasium import spaces
import numpy as np
import pandas as pd

class TradingEnv(gym.Env):
    metadata = {'render_modes': ['human']}

    def __init__(self, features_df, prices_df, render_mode=None):
        super(TradingEnv, self).__init__()
        self.features_df = features_df
        self.prices_df = prices_df
        # ... (rest of __init__ is the same)
        self.initial_balance = 100000
        self.trade_fee_percent = 0.001
        self.render_mode = render_mode
        self.action_space = spaces.Discrete(3)
        self.observation_space = spaces.Box(
            low=-np.inf, high=np.inf, shape=(len(self.features_df.columns),), dtype=np.float32
        )

    def _get_obs(self):
        return self.features_df.iloc[self.current_step].values.astype(np.float32)

    def reset(self, seed=None):
        # ... (reset method is the same)
        super().reset(seed=seed)
        self.balance = self.initial_balance
        self.net_worth = self.initial_balance
        self.shares_held = 0
        self.current_step = 0
        self.done = False
        obs = self._get_obs()
        info = {}
        return obs, info

    def step(self, action):
        # ... (most of step method is the same)
        if self.done:
            return self.reset()

        prev_net_worth = self.net_worth
        current_price = self.prices_df.iloc[self.current_step]['Close']
        if action == 1:
            if self.balance > current_price:
                self.shares_held += 1
                self.balance -= current_price * (1 + self.trade_fee_percent)
        elif action == 2:
            if self.shares_held > 0:
                self.shares_held -= 1
                self.balance += current_price * (1 - self.trade_fee_percent)
        
        self.net_worth = self.balance + (self.shares_held * current_price)
        reward = self.net_worth - prev_net_worth
        self.current_step += 1
        
        if self.current_step >= len(self.features_df) - 1:
            self.done = True
        
        # --- REMOVED THE RENDER CALL FROM HERE ---
        obs = self._get_obs()
        info = {}
        return obs, reward, self.done, False, info

    def render(self):
        """Renders the environment (e.g., prints status)"""
        # ... (render method is the same)
        if self.render_mode == 'human':
            print(f'Step: {self.current_step}, Net Worth: {self.net_worth:,.2f}, Shares Held: {self.shares_held}')