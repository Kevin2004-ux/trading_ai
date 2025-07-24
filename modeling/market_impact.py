# modeling/market_impact.py

import pandas as pd

def calculate_market_impact_score(features_df: pd.DataFrame) -> float:
    """
    Analyzes the most recent features to generate a "market impact" or
    "crowdedness" score.

    Returns:
        A score, typically from -1 (very crowded, high risk) to 0.
    """
    if features_df.empty:
        return 0.0

    # Get the most recent data point
    latest_features = features_df.iloc[-1]

    # Use relative volume as our primary metric for "crowdedness"
    # A value of 1.0 is average volume. A value of 3.0 means 3x average volume.
    relative_volume = latest_features.get('relative_volume', 1.0)

    # Simple model: The more volume is above average, the more crowded the trade is,
    # which increases the risk of reversal. We'll create a negative score.
    # We use max(0, ...) so the score is only negative when volume is above average.
    impact_score = -1 * max(0, relative_volume - 1.5) / 5

    # Ensure the score is capped at -1
    impact_score = max(-1.0, impact_score)

    return impact_score


if __name__ == "__main__":
    # --- Let's test it with some example data ---

    # Example 1: Average day
    avg_day_data = {'relative_volume': [1.1]}
    avg_df = pd.DataFrame(avg_day_data)
    avg_score = calculate_market_impact_score(avg_df)
    print(f"Impact score on an average volume day: {avg_score:.4f}")

    # Example 2: Very crowded day (e.g., after a big news event)
    crowded_day_data = {'relative_volume': [4.0]}
    crowded_df = pd.DataFrame(crowded_day_data)
    crowded_score = calculate_market_impact_score(crowded_df)
    print(f"Impact score on a very crowded day: {crowded_score:.4f}")