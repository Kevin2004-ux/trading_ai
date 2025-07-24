# FILE: vetting_pipeline.py

import pandas as pd
import numpy as np
import json
from sklearn.cluster import KMeans
from sklearn.preprocessing import StandardScaler
from tqdm import tqdm
import config
import requests
import argparse # <-- NEW IMPORT

def fetch_full_data_for_patterns(patterns):
    """Fetches the full historical data needed to extract windows for all patterns."""
    print("Fetching full historical data for all tickers...")
    full_data = {}
    tickers = set(p['ticker'] for p in patterns)
    for ticker in tickers:
        url = f"https://api.polygon.io/v2/aggs/ticker/{ticker}/range/1/day/2018-01-01/2025-12-31?adjusted=true&sort=asc&limit=50000&apiKey={config.POLYGON_API_KEY}"
        try:
            response = requests.get(url)
            response.raise_for_status()
            data = response.json()
            if 'results' in data and data['results']:
                df = pd.DataFrame(data['results'])
                df['Date'] = pd.to_datetime(df['t'], unit='ms')
                df.set_index('Date', inplace=True)
                df.index = df.index.normalize()
                df.rename(columns={'o': 'Open', 'h': 'High', 'l': 'Low', 'c': 'Close', 'v': 'Volume'}, inplace=True)
                full_data[ticker] = df
        except requests.exceptions.RequestException as e:
            print(f"  Could not fetch data for {ticker}: {e}")
    return full_data

def get_robust_start_index(data, start_date):
    try:
        return data.index.get_loc(start_date)
    except KeyError:
        try:
            loc = data.index.searchsorted(start_date, side='left')
            return loc if loc < len(data.index) else None
        except Exception:
            return None

def extract_pattern_windows(patterns, full_data, window_size=30):
    print("Extracting pattern windows from historical data...")
    windows, valid_patterns = [], []
    for p in tqdm(patterns, desc="Extracting Windows"):
        ticker, start_date = p['ticker'], pd.to_datetime(p['date'])
        if ticker in full_data:
            data = full_data[ticker]
            start_idx = get_robust_start_index(data, start_date)
            if start_idx is not None and (start_idx + window_size) <= len(data):
                window = data.iloc[start_idx : start_idx + window_size]['Close'].values
                scaler = StandardScaler()
                normalized_window = scaler.fit_transform(window.reshape(-1, 1)).flatten()
                windows.append(normalized_window)
                p['original_index'] = len(valid_patterns)
                valid_patterns.append(p)
    return np.array(windows), valid_patterns

# --- FUNCTION MODIFIED to accept validation date range ---
def backtest_cluster(cluster_patterns, full_data, val_start, val_end, window_size=30, time_horizon=15):
    """
    Backtests all patterns within a cluster on the validation data slice.
    """
    wins, losses, pct_changes = 0, 0, []
    profit_target_multiplier, stop_loss_multiplier = 3.75, 1.5
    
    val_start_dt = pd.to_datetime(val_start)
    val_end_dt = pd.to_datetime(val_end)

    for p in cluster_patterns:
        # --- NEW: Check if the pattern occurred within the validation window ---
        pattern_date = pd.to_datetime(p['date'])
        if not (val_start_dt <= pattern_date <= val_end_dt):
            continue

        ticker = p['ticker']
        if ticker not in full_data: continue
        
        data = full_data[ticker]
        start_idx = get_robust_start_index(data, pattern_date)
        if start_idx is None or start_idx + window_size + time_horizon > len(data): continue
        
        entry_price_signal = data.iloc[start_idx + window_size - 1]['Close']
        entry_price_with_slippage = entry_price_signal * (1 + config.SLIPPAGE_PERCENT)
        
        position_size, shares_traded = 10000, position_size / entry_price_with_slippage
        commission = shares_traded * config.COMMISSION_PER_SHARE * 2
        
        atr_window = data.iloc[start_idx : start_idx + window_size]
        atr = (atr_window['High'] - atr_window['Low']).mean()
        if atr == 0 or pd.isna(atr): continue

        profit_target, stop_loss = entry_price_signal + (atr * profit_target_multiplier), entry_price_signal - (atr * stop_loss_multiplier)
        future_data = data.iloc[start_idx + window_size : start_idx + window_size + time_horizon]
        
        trade_outcome, exit_price = 0, 0
        for _, future_row in future_data.iterrows():
            if future_row['High'] >= profit_target:
                trade_outcome, exit_price = 1, profit_target
                break
            if future_row['Low'] <= stop_loss:
                trade_outcome, exit_price = -1, stop_loss
                break
        
        if trade_outcome == 1:
            profit = (exit_price - entry_price_with_slippage) * shares_traded - commission
            if profit > 0: wins += 1
            else: losses += 1
            pct_changes.append((profit / position_size) * 100)
        elif trade_outcome == -1:
            loss_amount = (entry_price_with_slippage - exit_price) * shares_traded + commission
            losses += 1
            pct_changes.append(-(loss_amount / position_size) * 100)

    return wins, losses, pct_changes

# --- MAIN FUNCTION MODIFIED to accept validation date arguments ---
def main():
    """Main pipeline to cluster, filter, and validate discovered patterns."""
    parser = argparse.ArgumentParser(description="Run the vetting pipeline for a specific validation date range.")
    parser.add_argument('--val-start', required=True, help="Validation start date in YYYY-MM-DD format")
    parser.add_argument('--val-end', required=True, help="Validation end date in YYYY-MM-DD format")
    args = parser.parse_args()

    try:
        with open("discovered_patterns.jsonl", "r") as f:
            raw_patterns = [json.loads(line) for line in f]
    except FileNotFoundError:
        print("Error: discovered_patterns.jsonl not found. Run discovery_pipeline.py first."); return

    full_data = fetch_full_data_for_patterns(raw_patterns)
    windows, valid_patterns = extract_pattern_windows(raw_patterns, full_data)
    if len(windows) == 0: print("No valid pattern windows could be extracted. Exiting."); return

    print(f"\nClustering {len(windows)} windows into prototype patterns...")
    num_clusters = min(20, len(windows))
    kmeans = KMeans(n_clusters=num_clusters, random_state=42, n_init='auto').fit(windows)
    
    print(f"Applying statistical filters using validation period: {args.val_start} to {args.val_end}...")
    vetted_patterns = []
    for i in range(num_clusters):
        cluster_indices = np.where(kmeans.labels_ == i)[0]
        if len(cluster_indices) < 10: continue

        patterns_in_cluster = [valid_patterns[j] for j in cluster_indices]
        # --- PASSING DATE ARGS to the backtester ---
        wins, losses, pct_changes = backtest_cluster(patterns_in_cluster, full_data, args.val_start, args.val_end)
        
        total = wins + losses
        if total == 0: continue
        up_rate = wins / total
        if up_rate < 0.60: continue

        prototype_name = f"Prototype_Cluster_{i}"
        print(f"  ✔ Validated Pattern: {prototype_name} (Up Rate: {up_rate:.1%}, Occurrences: {total})")
        
        vetted_patterns.append({
            "pattern_id": prototype_name, "events": [p['id'] for p in patterns_in_cluster],
            "up_rate": up_rate, "down_rate": losses / total,
            "mean_move": np.mean(pct_changes) if pct_changes else 0,
            "sd_move": np.std(pct_changes) if len(pct_changes) > 1 else 0,
            "sample_size": total
        })
        
    output_file = "vetted_patterns.jsonl"
    with open(output_file, "w") as f:
        for p in vetted_patterns: f.write(json.dumps(p) + "\n")
        
    print(f"\nPhase 2 & 3 Complete. Distilled {len(raw_patterns)} raw motifs into {len(vetted_patterns)} validated patterns saved to {output_file}.")

if __name__ == "__main__":
    main()