# pipeline/etl_jobs.py

import os
from datetime import datetime, timedelta
import pandas as pd
from data_ingest import PolygonClient

# Define where our local data will be stored
DATA_STORAGE_PATH = "feature_store"


def run_daily_stock_etl(ticker: str, date_to_fetch: str):
    """
    An ETL job to fetch one day of stock data and save it locally.
    Airflow will call this function for each day and ticker.
    """
    print(f"--- Running ETL for {ticker} on {date_to_fetch} ---")

    # Ensure the main storage directory exists
    os.makedirs(DATA_STORAGE_PATH, exist_ok=True)

    # Create a path specific to this ticker
    ticker_path = os.path.join(DATA_STORAGE_PATH, ticker)
    os.makedirs(ticker_path, exist_ok=True)

    # Initialize our tested, reliable client
    client = PolygonClient()

    # Fetch a single day's data
    start_date = datetime.strptime(date_to_fetch, '%Y-%m-%d')
    # The Polygon API range is inclusive, so start and end can be the same day
    end_date = start_date 

    daily_data_df = client.get_historical(ticker, start_date, end_date)

    if not daily_data_df.empty:
        # Save the data to a high-performance Parquet file
        output_file = os.path.join(ticker_path, f"{date_to_fetch}.parquet")
        daily_data_df.to_parquet(output_file)
        print(f"✅ Successfully saved data to {output_file}")
    else:
        print(f"⚠️ No data found for {ticker} on {date_to_fetch}. Skipping file save.")

# Example of how to run this job manually for testing
if __name__ == "__main__":
    # Get yesterday's date as a string
    yesterday = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
    run_daily_stock_etl(ticker="SPY", date_to_fetch=yesterday)