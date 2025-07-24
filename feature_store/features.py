# feature_store/features.py
import pandas as pd

def calculate_technical_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Takes a raw OHLCV DataFrame and adds technical indicator columns.
    """
    # Make a copy to avoid changing the original DataFrame
    features_df = df.copy()

    # Feature 1: Simple Moving Average (SMA)
    features_df['sma_50'] = features_df['close'].rolling(window=50).mean()
    
    # Feature 2: Relative Strength Index (RSI)
    delta = features_df['close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / loss
    features_df['rsi'] = 100 - (100 / (1 + rs))

    # Feature 3: Moving Average Convergence Divergence (MACD)
    exp1 = features_df['close'].ewm(span=12, adjust=False).mean()
    exp2 = features_df['close'].ewm(span=26, adjust=False).mean()
    features_df['macd'] = exp1 - exp2

    # Feature 4: Relative Volume
    # Compares the current volume to its 50-day average.
    features_df['relative_volume'] = features_df['volume'] / features_df['volume'].rolling(window=50).mean()

    # Drop rows with NaN values created by rolling windows
    features_df.dropna(inplace=True)
    
    return features_df