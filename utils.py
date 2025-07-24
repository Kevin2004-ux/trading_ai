# FILE: utils.py

import pandas as pd
import numpy as np
import requests
import config
import time
# --- NEW IMPORT ---
import pandas_datareader.data as web

def fetch_fred_data(start_date, end_date):
    """
    Fetches key macro and cross-asset data from FRED.
    """
    print("  Fetching Macro & Cross-Asset data from FRED...")
    try:
        # T10Y2Y: 10-Year Treasury Constant Maturity Minus 2-Year Treasury Constant Maturity
        # UNRATE: Civilian Unemployment Rate
        # UMCSENT: University of Michigan: Consumer Sentiment
        # VIXCLS: CBOE Volatility Index
        fred_series = ['T10Y2Y', 'UNRATE', 'UMCSENT', 'VIXCLS']
        
        # Fetch data using pandas_datareader
        fred_df = web.DataReader(fred_series, 'fred', start_date, end_date)
        
        # FRED data is often monthly or weekly. We forward-fill to apply the last known value to each day.
        fred_df.ffill(inplace=True)
        return fred_df
    except Exception as e:
        print(f"  Could not fetch FRED data: {e}")
        return None

def fetch_market_data(start_date, end_date):
    """Fetches S&P 500 (SPY) data to determine the market regime."""
    print("  Fetching S&P 500 data for market regime analysis...")
    time.sleep(1) # Add a small delay to respect API rate limits
    try:
        url = f"https://api.polygon.io/v2/aggs/ticker/SPY/range/1/day/{start_date}/{end_date}?adjusted=true&sort=asc&limit=50000&apiKey={config.POLYGON_API_KEY}"
        response = requests.get(url)
        response.raise_for_status()
        data = response.json()['results']
        market_df = pd.DataFrame(data)
        market_df['Date'] = pd.to_datetime(market_df['t'], unit='ms')
        market_df = market_df[['Date', 'c']].rename(columns={'c': 'SPY_Close'})
        market_df.set_index('Date', inplace=True)
        return market_df
    except Exception as e:
        print(f"  Could not fetch SPY data: {e}")
        return None

def add_market_regime(df):
    """Adds a market regime flag based on the S&P 500's 200-day moving average."""
    if df.index.empty: return df
    start_date, end_date = df.index.min(), df.index.max()
    spy_df = fetch_market_data(start_date.strftime('%Y-%m-%d'), end_date.strftime('%Y-%m-%d'))
    if spy_df is None:
        df['regime'] = 0
        return df
    spy_df['SMA_200'] = spy_df['SPY_Close'].rolling(window=200).mean()
    spy_df['regime'] = np.where(spy_df['SPY_Close'] > spy_df['SMA_200'], 1, 0)
    df = df.join(spy_df['regime'])
    df['regime'] = df['regime'].ffill().fillna(0)
    return df

def add_features(df):
    """
    Adds technical, macro, and cross-asset features to the DataFrame.
    """
    print("  Adding features (Technical, Macro, Cross-Asset)...")
    
    # --- MERGE MACRO DATA ---
    # Fetch FRED data for the date range of the stock data
    if not df.index.empty:
        start_date, end_date = df.index.min(), df.index.max()
        fred_df = fetch_fred_data(start_date, end_date)
        if fred_df is not None:
            # Use merge_asof to join daily stock data with less frequent macro data
            df = pd.merge_asof(df.sort_index(), fred_df.sort_index(), left_index=True, right_index=True, direction='backward')

    # Standard technical indicators
    df['Volume'] = pd.to_numeric(df['Volume'], errors='coerce').fillna(0)
    df['SMA_50'] = df['Close'].rolling(window=50).mean()
    typical_price = (df['High'] + df['Low'] + df['Close']) / 3
    df['VWAP'] = (typical_price * df['Volume']).cumsum() / df['Volume'].cumsum()
    df['high_low'] = df['High'] - df['Low']
    df['high_close'] = np.abs(df['High'] - df['Close'].shift())
    df['low_close'] = np.abs(df['Low'] - df['Close'].shift())
    df['true_range'] = df[['high_low', 'high_close', 'low_close']].max(axis=1)
    df['ATR'] = df['true_range'].rolling(window=14).mean()
    delta = df['Close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / loss
    df['RSI'] = 100 - (100 / (1 + rs))
    exp1 = df['Close'].ewm(span=12, adjust=False).mean()
    exp2 = df['Close'].ewm(span=26, adjust=False).mean()
    df['MACD'] = exp1 - exp2
    df['MACD_signal'] = df['MACD'].ewm(span=9, adjust=False).mean()
    df['SMA_50_slope'] = df['SMA_50'].diff(5) / df['SMA_50'] * 100
    df['Relative_Volume'] = df['Volume'] / df['Volume'].rolling(window=50).mean()
    
    df.dropna(inplace=True)
    df = add_market_regime(df)
    
    print("  Feature and regime engineering complete.")
    return df