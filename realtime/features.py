import pandas as pd
import numpy as np
import os
import sys

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import config
from utils import add_features
from discovery_pipeline import fetch_polygon_data
from realtime.similarity import get_similarity_forecast

def get_latest_feature_vector(ticker, for_date=None):
    """
    Builds the feature vector for a ticker. Can now get data for a specific
    historical date for backtesting purposes.

    Args:
        ticker (str): The stock ticker.
        for_date (pd.Timestamp, optional): If provided, gets data as of this date.
                                           If None, gets the latest live data.
    """
    print(f"\n--- Building feature vector for {ticker} as of {for_date.date() if for_date else 'LATEST'} ---")
    
    # --- THIS IS THE NEW LOGIC ---
    if for_date:
        end_date = for_date
    else:
        end_date = pd.to_datetime('today')
    
    # We need about 18 months of prior data to calculate all the features
    start_date = end_date - pd.DateOffset(months=18)
    # --- END OF NEW LOGIC ---
    
    df = fetch_polygon_data(ticker, start_date.strftime('%Y-%m-%d'), end_date.strftime('%Y-%m-%d'))
    if df is None or df.empty:
        print(f"Could not fetch sufficient historical data for {ticker}.")
        return None, None
        
    df_with_features = add_features(df)
    if df_with_features.empty:
        print(f"DataFrame for {ticker} is empty after feature engineering.")
        return None, None

    # Get the most recent row of data from the dataframe
    latest_data = df_with_features.iloc[-1]
    
    # ... (the rest of the function remains the same)
    
    base_feature_names = [
        'SMA_50_slope', 'Relative_Volume', 'RSI', 'MACD', 'regime', 'ATR',
        'T10Y2Y', 'UNRATE', 'UMCSENT', 'VIXCLS'
    ]
    # In a full system, you would add the sentiment/analyst features here too
    
    for col in base_feature_names:
        if col not in latest_data.index:
            latest_data[col] = 0
            
    base_feature_vector = latest_data[base_feature_names].values.astype(float)
    
    # For backtesting, we can disable the live similarity search for speed/simplicity
    ŷ_sim = 0.0 # get_similarity_forecast(base_feature_vector)
    
    # The first feature in our model is the similarity score
    final_feature_vector = np.insert(base_feature_vector, 0, ŷ_sim)

    return final_feature_vector, latest_data