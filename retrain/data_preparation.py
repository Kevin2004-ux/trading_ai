# retrain/data_preparation.py
import pandas as pd
from datetime import datetime, timedelta
import numpy as np
import sys
sys.path.append('.')

from data_ingest import PolygonClient
from feature_store.features import calculate_technical_features
from modeling.regime import RegimeDetector
from meta_controller.run_config import RunConfig

def prepare_training_data(ticker: str, cfg: RunConfig) -> pd.DataFrame:
    print(f"--- Preparing training data for {ticker} (threshold={cfg.profit_threshold:.2f}) ---")
    client = PolygonClient()
    end_date, start_date = datetime.now(), datetime.now() - timedelta(days=cfg.history_years * 365)
    
    ohlcv_df = client.get_historical(ticker, start_date, end_date)
    if ohlcv_df.empty: return pd.DataFrame()

    technical_features = calculate_technical_features(ohlcv_df)
    
    regime_detector = RegimeDetector(n_regimes=3)
    regime_detector.fit(ohlcv_df)
    regime_labels = regime_detector.predict(ohlcv_df)
    
    future_returns = ohlcv_df['close'].pct_change(periods=cfg.future_days).shift(-cfg.future_days)
    conditions = [
      (future_returns >  cfg.profit_threshold),
      (future_returns < -cfg.profit_threshold),
    ]
    choices = [2, 0]
    target_series = pd.Series(np.select(conditions, choices, default=1), index=ohlcv_df.index, name="target")

    combined_df = technical_features.join(regime_labels).join(target_series)
    combined_df.dropna(inplace=True)
    
    print(f"✅ Training data prepared and aligned successfully ({len(combined_df)} rows).")
    return combined_df