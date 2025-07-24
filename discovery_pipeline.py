# FILE: discovery_pipeline.py

import pandas as pd
import numpy as np
import stumpy
import requests
import config
import json
from tqdm import tqdm
import argparse # <-- NEW IMPORT

# --- FUNCTION MODIFIED to accept date ranges ---
def fetch_polygon_data(ticker, start_date, end_date):
    """Fetches historical daily data from Polygon.io for a specific date range."""
    print(f"Fetching data for {ticker} from {start_date} to {end_date} from Polygon.io...")
    # --- URL UPDATED to use date variables ---
    url = f"https://api.polygon.io/v2/aggs/ticker/{ticker}/range/1/day/{start_date}/{end_date}?adjusted=true&sort=asc&limit=50000&apiKey={config.POLYGON_API_KEY}"
    try:
        response = requests.get(url)
        response.raise_for_status()
        data = response.json()
        if 'results' not in data or not data['results']:
            print(f"No data found for {ticker}.")
            return None
        df = pd.DataFrame(data['results'])
        df['Date'] = pd.to_datetime(df['t'], unit='ms')
        df.set_index('Date', inplace=True)
        df.rename(columns={'o': 'Open', 'h': 'High', 'l': 'Low', 'c': 'Close', 'v': 'Volume'}, inplace=True)
        return df[['Open', 'High', 'Low', 'Close', 'Volume']]
    except requests.exceptions.RequestException as e:
        print(f"Error fetching data from Polygon: {e}")
        return None

def find_motifs(ticker, data, window_size=30, num_motifs=100):
    """Uses the Matrix Profile to discover the top K motifs in the price series."""
    print(f"  Discovering top {num_motifs} motifs for {ticker} with a {window_size}-day window...")
    close_prices = data['Close'].values
    if len(close_prices) < window_size * 2:
        print("  Not enough data to perform motif discovery.")
        return []

    matrix_profile = stumpy.stump(close_prices, m=window_size)
    motif_indices = np.argsort(matrix_profile[:, 0])[:num_motifs]
    print(f"  Found {len(motif_indices)} potential motif starting points.")
    
    discovered_patterns = []
    for idx in motif_indices:
        pattern_date = data.index[idx].date()
        pattern_id = f"{ticker}_Motif_{pattern_date}"
        dossier = f"A raw, repeating price pattern (motif) was discovered for {ticker} starting on {pattern_date}."
        discovered_patterns.append({
            "id": pattern_id,
            "pattern_signature": f"{ticker}_MotifDiscovery_{window_size}",
            "ticker": ticker,
            "date": str(pattern_date),
            "outcome": "untested",
            "pct_change": 0,
            "dossier": dossier
        })
    return discovered_patterns

# --- MAIN FUNCTION MODIFIED to accept date arguments ---
def main():
    """Main pipeline to fetch data and discover raw patterns for a given period."""
    parser = argparse.ArgumentParser(description="Run the motif discovery pipeline for a specific date range.")
    parser.add_argument('--start', required=True, help="Start date in YYYY-MM-DD format")
    parser.add_argument('--end', required=True, help="End date in YYYY-MM-DD format")
    args = parser.parse_args()

    all_patterns = []
    for ticker in config.STOCKS_TO_MONITOR:
        data = fetch_polygon_data(ticker, args.start, args.end)
        if data is not None:
            patterns = find_motifs(ticker, data)
            all_patterns.extend(patterns)
    
    output_file = "discovered_patterns.jsonl"
    with open(output_file, "w") as f:
        for p in all_patterns:
            f.write(json.dumps(p) + "\n")
    print(f"\nPhase 1 Complete. Discovered {len(all_patterns)} raw motif instances saved to {output_file}.")

if __name__ == "__main__":
    main()