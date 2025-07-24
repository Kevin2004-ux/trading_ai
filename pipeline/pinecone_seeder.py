# pipeline/pinecone_seeder.py

import os
import pandas as pd
from pinecone import Pinecone, ServerlessSpec
from dotenv import load_dotenv

# Add sys path to import from other folders
import sys
sys.path.append('.')

from retrain.data_preparation import prepare_training_data

# --- Configuration ---
INDEX_NAME = "trading-patterns"
load_dotenv(override=True)

def seed_pinecone():
    """
    Fetches historical data, extracts feature vectors, and "seeds" them
    into a Pinecone index for similarity searching.
    """
    api_key = os.getenv("PINECONE_API_KEY")
    environment = os.getenv("PINECONE_ENVIRONMENT")
    
    print("--- DEBUGGING INFO ---")
    print(f"Loaded API Key: ...{api_key[-4:] if api_key else 'Not Found'}")
    print(f"Loaded Environment: {environment}")
    print("----------------------")
    
    if not api_key or not environment:
        raise ValueError("PINECONE_API_KEY and PINECONE_ENVIRONMENT must be set in your .env file")

    pc = Pinecone(api_key=api_key)

    if INDEX_NAME not in pc.list_indexes().names():
        print(f"Creating new Pinecone index: {INDEX_NAME}")
        pc.create_index(
            name=INDEX_NAME,
            dimension=3,
            metric="cosine",
            spec=ServerlessSpec(cloud="aws", region=environment)
        )
    
    index = pc.Index(INDEX_NAME)
    print("Pinecone index is ready.")

    historical_data = prepare_training_data(ticker="SPY", history_years=3)
    
    if historical_data.empty:
        print("Cannot seed Pinecone. No historical data found.")
        return

    print(f"Preparing {len(historical_data)} vectors for Pinecone...")
    vectors_to_upsert = []
    feature_list = ['sma_50', 'rsi', 'macd'] 

    for i, row in historical_data.iterrows():
        vector_id = f"vec_{row.name.strftime('%Y-%m-%d')}"
        feature_vector = row[feature_list].values.tolist()
        metadata = {"outcome": int(row['target'])}
        
        vectors_to_upsert.append({
            "id": vector_id,
            "values": feature_vector,
            "metadata": metadata
        })

    batch_size = 100
    print(f"Upserting {len(vectors_to_upsert)} vectors in batches of {batch_size}...")
    # The 'delete' line that was here has been removed.
    for i in range(0, len(vectors_to_upsert), batch_size):
        batch = vectors_to_upsert[i : i + batch_size]
        index.upsert(vectors=batch)

    print("--- ✅ Pinecone Seeding Complete ---")
    print(f"Index '{INDEX_NAME}' now contains {index.describe_index_stats()['total_vector_count']} vectors.")


if __name__ == "__main__":
    seed_pinecone()