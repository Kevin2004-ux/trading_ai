# utils.py

import pandas as pd
import numpy as np

def add_features(df):
    """
    Adds technical indicators (features) to the DataFrame.
    """
    print("  Adding technical features (SMA, VWAP, ATR)...")
    df['SMA_50'] = df['Close'].rolling(window=50).mean()
    
    # Ensure Volume is numeric and handle potential non-numeric values
    df['Volume'] = pd.to_numeric(df['Volume'], errors='coerce').fillna(0)
    
    typical_price = (df['High'] + df['Low'] + df['Close']) / 3
    df['VWAP'] = (typical_price * df['Volume']).cumsum() / df['Volume'].cumsum()
    
    df['high_low'] = df['High'] - df['Low']
    df['high_close'] = np.abs(df['High'] - df['Close'].shift())
    df['low_close'] = np.abs(df['Low'] - df['Close'].shift())
    df['true_range'] = df[['high_low', 'high_close', 'low_close']].max(axis=1)
    
    df['ATR'] = df['true_range'].rolling(window=14).mean()
    
    df.dropna(inplace=True)
    return df
