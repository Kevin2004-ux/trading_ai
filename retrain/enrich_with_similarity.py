# retrain/enrich_with_similarity.py

import pandas as pd
from tqdm import tqdm

import sys
sys.path.append('.')

from retrain.data_preparation import prepare_training_data
from modeling.similarity_search import find_similar_patterns
from data_ingest.alternative_data import get_average_sentiment

def enrich_data_with_all_features():
    """
    Takes the base data and enriches it with both similarity and sentiment scores.
    """
    TICKER = "SPY"
    
    # 1. Get the base data
    base_data = prepare_training_data(ticker=TICKER, history_years=3)
    if base_data.empty:
        print("Could not prepare base data. Exiting.")
        return

    # 2. Get the single average sentiment score for the ticker
    avg_sentiment = get_average_sentiment(TICKER)

    # 3. Get the similarity score for each day
    similarity_scores = []
    base_features = ['sma_50', 'rsi', 'macd']
    
    # tqdm adds a nice progress bar
    for index, row in tqdm(base_data.iterrows(), total=base_data.shape[0], desc="Enriching data"):
        feature_vector = row[base_features].values.tolist()
        score, _ = find_similar_patterns(feature_vector)
        similarity_scores.append(score)

    # 4. Add the new features to our DataFrame
    enriched_data = base_data.copy()
    enriched_data['similarity_score'] = similarity_scores
    enriched_data['sentiment_score'] = avg_sentiment # Apply the same score to all historical rows
    
    # 5. Save the final dataset with the correct name
    output_path = "swing_training_data_final.parquet"
    enriched_data.to_parquet(output_path)
    print(f"\n✅ Final enriched data saved to {output_path}")

if __name__ == "__main__":
    enrich_data_with_all_features()