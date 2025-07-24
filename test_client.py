# test_client.py

from datetime import datetime
from data_ingest.clients import PolygonClient, PolygonOptionsClient

def test_stock_client():
    """Tests the PolygonClient for historical stock data."""
    print("\n--- 🧪 Testing Stock Client ---")
    try:
        client = PolygonClient()
        start_date = datetime(2024, 1, 1)
        end_date = datetime(2024, 1, 31)
        data_df = client.get_historical("AAPL", start_date, end_date)
        
        if not data_df.empty:
            print(f"✅ Success! Fetched {len(data_df)} stock bars for AAPL.")
            print(data_df.tail(3))
        else:
            print("❌ Test failed for Stock Client.")
    except Exception as e:
        print(f"An error occurred during stock client test: {e}")

def test_options_client():
    """Tests the PolygonOptionsClient for options chain data."""
    print("\n--- 🧪 Testing Options Client ---")
    try:
        client = PolygonOptionsClient()
        # Note: Fetching an entire option chain can take a few seconds
        chain_df = client.get_option_chain("AAPL")
        
        if not chain_df.empty:
            print(f"✅ Success! Fetched {len(chain_df)} total option contracts for AAPL.")
            # Let's display a few columns for the first 5 contracts
            print("Sample of option chain data:")
            print(chain_df[['ticker', 'expiration_date', 'strike_price', 'contract_type']].head())
        else:
            print("❌ Test failed for Options Client.")
    except Exception as e:
        print(f"An error occurred during options client test: {e}")

if __name__ == "__main__":
    test_stock_client()
    test_options_client()
    print("\n--- ✅ All Tests Complete ---")