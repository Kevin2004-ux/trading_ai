# retrain/options_data_preparation.py

import pandas as pd
from datetime import datetime, timedelta
import time
import numpy as np

# Add sys path to import from other folders
import sys
sys.path.append('.')

from data_ingest import PolygonClient, PolygonOptionsClient
from feature_store.options_features import calculate_options_features


def prepare_options_training_data(ticker: str, history_date: datetime, look_forward_days: int = 10) -> pd.DataFrame:
    """
    Fetches historical option chains and labels them based on the
    underlying stock's future performance.
    """
    print(f"--- Preparing options training data for {ticker} as of {history_date.date()} ---")
    
    options_client = PolygonOptionsClient()
    stock_client = PolygonClient()
    
    # 1. Get the option chain and stock price from the historical date
    date_str = history_date.strftime('%Y-%m-%d')
    chain_df = options_client.get_option_chain(ticker, as_of=date_str)
    
    # Fetch a small window of stock data to get the price
    stock_data_t1 = stock_client.get_historical(ticker, history_date - timedelta(days=5), history_date)
    
    if chain_df.empty or stock_data_t1.empty:
        print(f"Could not fetch initial data for {history_date.date()}. It may be a weekend or holiday.")
        return pd.DataFrame()
    
    price_t1 = stock_data_t1.iloc[-1]['close']
    
    # 2. Get the stock price N days in the future to determine the outcome
    future_date = history_date + timedelta(days=look_forward_days)
    stock_data_t2 = stock_client.get_historical(ticker, future_date - timedelta(days=5), future_date)
    
    if stock_data_t2.empty:
        print(f"Could not fetch stock data for the future date {future_date.date()}.")
        return pd.DataFrame()
        
    price_t2 = stock_data_t2.iloc[-1]['close']

    # 3. Calculate the "target score" based on the stock's move
    stock_price_change = price_t2 - price_t1
    
    # For calls, the score is positive if the stock went up.
    # For puts, the score is positive if the stock went down (stock_price_change is negative).
    chain_df['target_score'] = np.where(
        chain_df['contract_type'] == 'call',
        stock_price_change,
        -stock_price_change 
    )
    
    # 4. Calculate features for the option chain
    features_df = calculate_options_features(chain_df, price_t1)
    
    print(f"✅ Options training data prepared successfully for {len(features_df)} contracts.")
    return features_df


if __name__ == "__main__":
    historical_date = datetime.now() - timedelta(days=30)
    
    while historical_date.weekday() >= 5:
        historical_date -= timedelta(days=1)

    options_training_data = prepare_options_training_data("SPY", historical_date)
    
    if not options_training_data.empty:
        print("\nSample of the final options training data:")
        display_cols = ['ticker', 'strike_price', 'time_to_expiration', 'moneyness', 'target_score']
        print(options_training_data[display_cols].sort_values(by='target_score', ascending=False).head())