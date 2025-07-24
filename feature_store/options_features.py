# feature_store/options_features.py

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from py_vollib.black_scholes import implied_volatility as iv
from py_vollib.black_scholes.greeks import analytical as greeks

# Add sys path to import from other folders
import sys
sys.path.append('.')

from data_ingest import PolygonClient, PolygonOptionsClient


def calculate_options_features(options_df: pd.DataFrame, underlying_price: float) -> pd.DataFrame:
    """
    Takes a raw options chain DataFrame and enriches it with key features,
    including calculated Greeks and Implied Volatility.
    """
    if options_df.empty:
        return pd.DataFrame()
        
    features_df = options_df.copy()
    features_df['expiration_date'] = pd.to_datetime(features_df['expiration_date'])
    
    features_df['time_to_expiration_days'] = (features_df['expiration_date'] - datetime.now()).dt.days
    features_df['moneyness'] = underlying_price / features_df['strike_price']
    
    RISK_FREE_RATE = 0.05
    features_df['time_to_expiration_years'] = features_df['time_to_expiration_days'] / 365.25

    # --- CORRECTED CALCULATION LOGIC ---
    def calculate_metrics(row):
        try:
            flag = 'c' if row['contract_type'] == 'call' else 'p'
            option_price = row.get('close', 0.01)
            time_to_exp = row['time_to_expiration_years']
            strike = row['strike_price']
            
            # Return NaNs immediately if time to expiration is zero or less
            if time_to_exp <= 0:
                return pd.Series([np.nan] * 5)

            implied_vol = iv.implied_volatility(
                option_price, underlying_price, strike, time_to_exp, RISK_FREE_RATE, flag
            )
            
            # Calculate each Greek with its own function call
            delta = greeks.delta(flag, underlying_price, strike, time_to_exp, RISK_FREE_RATE, implied_vol)
            gamma = greeks.gamma(flag, underlying_price, strike, time_to_exp, RISK_FREE_RATE, implied_vol)
            theta = greeks.theta(flag, underlying_price, strike, time_to_exp, RISK_FREE_RATE, implied_vol)
            vega = greeks.vega(flag, underlying_price, strike, time_to_exp, RISK_FREE_RATE, implied_vol)
            
            return pd.Series([implied_vol, delta, gamma, theta, vega])
        except Exception:
            return pd.Series([np.nan] * 5)
    # --- END CORRECTION ---

    features_df[['implied_volatility', 'delta', 'gamma', 'theta', 'vega']] = features_df.apply(calculate_metrics, axis=1)

    features_df.drop(columns=['time_to_expiration_years'], inplace=True)
    features_df.dropna(inplace=True)
    
    print(f"✅ Calculated real features for {len(features_df)} option contracts.")
    return features_df


if __name__ == "__main__":
    stock_client = PolygonClient()
    today = datetime.now()
    start_date = today - timedelta(days=5)
    spy_data = stock_client.get_historical("SPY", start_date, today)
    
    if not spy_data.empty:
        current_price = spy_data.iloc[-1]['close']
        print(f"Current SPY price: {current_price}")

        options_client = PolygonOptionsClient()
        chain_df = options_client.get_option_chain("SPY", as_of=(today - timedelta(days=1)).strftime('%Y-%m-%d'))
        
        if not chain_df.empty:
            chain_df['close'] = np.where(
                chain_df['contract_type'] == 'call',
                (current_price - chain_df['strike_price']),
                (chain_df['strike_price'] - current_price)
            ).clip(min=0.01)

            options_with_features = calculate_options_features(chain_df, current_price)
            
            if not options_with_features.empty:
                print("\nSample of options data with REAL features:")
                display_cols = ['strike_price', 'contract_type', 'time_to_expiration_days', 'implied_volatility', 'delta']
                print(options_with_features[display_cols].head())