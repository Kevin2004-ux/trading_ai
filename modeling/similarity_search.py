# modeling/similarity_search.py

import os
import numpy as np
from pinecone import Pinecone
from dotenv import load_dotenv

# --- Configuration ---
INDEX_NAME = "trading-patterns"
load_dotenv(override=True)

def find_similar_patterns(current_feature_vector: list, top_k: int = 10) -> (float, list):
    """
    Queries the Pinecone index to find the most similar historical patterns.

    Args:
        current_feature_vector (list): A list of the latest features [sma_50, rsi, macd].
        top_k (int): The number of similar patterns to retrieve.

    Returns:
        A tuple containing:
        - The similarity-weighted forecast score.
        - A list of the matched historical patterns.
    """
    api_key = os.getenv("PINECONE_API_KEY")
    if not api_key:
        raise ValueError("PINECONE_API_KEY not found in .env file")

    pc = Pinecone(api_key=api_key)
    index = pc.Index(INDEX_NAME)

    print(f"Searching for the {top_k} most similar patterns...")
    query_results = index.query(
        vector=current_feature_vector,
        top_k=top_k,
        include_metadata=True
    )

    matches = query_results.get('matches', [])
    if not matches:
        return 0.0, []

    # Calculate a similarity-weighted forecast from the historical outcomes
    numerator = 0
    denominator = 0
    for match in matches:
        historical_outcome = match.metadata.get('outcome', 1) # Default to HOLD
        similarity_score = match.score

        # Outcome is 0=SELL, 1=HOLD, 2=BUY. We can map this to -1, 0, 1
        outcome_sentiment = historical_outcome - 1

        numerator += outcome_sentiment * similarity_score
        denominator += similarity_score

    weighted_forecast = numerator / denominator if denominator > 0 else 0.0

    return weighted_forecast, matches

# This allows us to run this script directly to test it
if __name__ == "__main__":
    # Let's pretend the current market has these features
    # (These are just example numbers)
    live_features = [450.0, 55.0, -2.5]

    forecast, similar_patterns = find_similar_patterns(live_features)

    print(f"\n--- ✅ Search Complete ---")
    print(f"Similarity-weighted forecast: {forecast:.4f}")
    print("\nTop 3 similar patterns found:")
    for pattern in similar_patterns[:3]:
        print(f"  - ID: {pattern.id}, Similarity: {pattern.score:.4f}, Historical Outcome: {pattern.metadata.get('outcome')}")