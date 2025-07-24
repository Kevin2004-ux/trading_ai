# modeling/regime.py

import pandas as pd
import numpy as np
from hmmlearn import hmm

class RegimeDetector:
    def __init__(self, n_regimes: int = 3):
        self.n_regimes = n_regimes
        self.model = hmm.GaussianHMM(
            n_components=n_regimes, 
            covariance_type="full", 
            n_iter=100,
            random_state=42,
            tol=0.01 # Increased tolerance for convergence
        )

    def fit(self, data: pd.DataFrame):
        print(f"---  Fitting HMM model to find {self.n_regimes} regimes... ---")
        hmm_features = self._prepare_hmm_features(data)
        if hmm_features is None:
            print("Could not generate HMM features.")
            return
        # Add a small amount of noise for stability
        noise = np.random.normal(0, 1e-4, hmm_features.shape)
        self.model.fit(hmm_features + noise)
        print("✅ HMM model fitted successfully.")

    def predict(self, data: pd.DataFrame) -> pd.Series:
        hmm_features = self._prepare_hmm_features(data)
        if hmm_features is None:
            return pd.Series(name="regime")
        regimes = self.model.predict(hmm_features)
        return pd.Series(regimes, index=data.index[-len(regimes):], name="regime")

    def _prepare_hmm_features(self, data: pd.DataFrame) -> np.ndarray | None:
        returns = data['close'].pct_change()
        volatility = returns.rolling(window=21).std() # 21 trading days in a month
        
        # Combine and remove any rows with NaN, which happens at the start
        aligned_data = pd.concat([returns, volatility], axis=1, join='inner')
        aligned_data.columns = ['returns', 'volatility']
        aligned_data.dropna(inplace=True)

        if len(aligned_data) < self.n_regimes:
            return None
            
        return aligned_data.values