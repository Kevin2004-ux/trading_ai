# test_model.py

from datetime import datetime, timedelta
from data_ingest import PolygonClient
from modeling import SwingTradePolicy

def run_prediction_test():
    print("--- 🧪 Running Model Prediction Test ---")

    # 1. Fetch real historical data to run our prediction on
    client = PolygonClient()
    # We need about 3 months of data to warm up the 50-day SMA
    start_date = datetime.now() - timedelta(days=90)
    end_date = datetime.now()

    print(f"Fetching data for SPY from {start_date.date()} to {end_date.date()}...")
    spy_data = client.get_historical("SPY", start_date, end_date)

    if spy_data.empty:
        print("❌ Could not fetch data for test. Aborting.")
        return

    print(f"✅ Data fetched. Passing to model for prediction...")

    # 2. Initialize our untrained model
    model = SwingTradePolicy()

    # 3. Ask the model for a decision
    decision = model.predict(spy_data)

    # 4. Print the result in a human-readable format
    action_map = {0: "SELL", 1: "HOLD", 2: "BUY"}
    print("\n---------------------------------")
    print(f"🧠 Model Decision: {action_map.get(decision, 'UNKNOWN')}")
    print("---------------------------------")
    print("(Note: This decision is from an untrained model and will be random.)")


if __name__ == "__main__":
    run_prediction_test()