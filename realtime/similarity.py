# FILE: realtime/similarity.py

import pinecone
import numpy as np
import os
import sys
import google.generativeai as genai

# Add the parent directory to the path so we can import our modules
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
import config

# --- Initialization ---
# NOTE: This assumes you have a Pinecone index populated with historical feature vectors.
# We have not built the script to do this yet, but we will build the query logic now.
INDEX_NAME = "feature-vector-library" # A new index for our feature vectors

try:
    pc = pinecone.Pinecone(api_key=config.PINECONE_API_KEY)
    genai.configure(api_key=config.GEMINI_API_KEY)
    
    if INDEX_NAME not in pc.list_indexes().names():
        print(f"Warning: Pinecone index '{INDEX_NAME}' does not exist. Similarity search will return 0.")
        index = None
    else:
        index = pc.Index(INDEX_NAME)

except Exception as e:
    print(f"Error initializing Pinecone or Gemini: {e}")
    index = None

def get_similarity_forecast(feature_vector, k=25):
    """
    Finds the K most similar historical vectors and computes a similarity-weighted forecast.
    """
    if index is None or feature_vector is None:
        return 0.0 # Return a neutral forecast if Pinecone isn't available

    try:
        # 1. Embed the live feature vector
        # To be comparable, the live vector must be converted into the same kind of embedding
        # as the historical vectors stored in Pinecone. We'll use a text representation for this.
        vector_str = ", ".join([f"{val:.4f}" for val in feature_vector])
        embedding_model = 'models/embedding-001'
        live_embedding = genai.embed_content(model=embedding_model, content=vector_str)["embedding"]
        
        # 2. Query Pinecone for the top K most similar vectors
        query_result = index.query(vector=live_embedding, top_k=k, include_metadata=True)
        matches = query_result.get('matches', [])
        
        if not matches:
            print("  Similarity search found no historical matches.")
            return 0.0

        # 3. Calculate the similarity-weighted forecast
        # This formula gives more weight to closer matches.
        numerator = 0
        denominator = 0
        
        for match in matches:
            # We assume the historical return is stored in the metadata
            historical_return = match.metadata.get('future_return', 0.0)
            similarity_score = match.score
            
            numerator += historical_return * similarity_score
            denominator += similarity_score
            
        if denominator == 0:
            return 0.0
            
        ŷ_sim = numerator / denominator
        print(f"  Similarity forecast based on {len(matches)} neighbors: {ŷ_sim:.4f}")
        return ŷ_sim

    except Exception as e:
        print(f"An error occurred during similarity search: {e}")
        return 0.0

def main():
    """
    Main function for testing the similarity search.
    """
    # Create a dummy feature vector for testing purposes
    # In the real pipeline, this comes from features.py
    # ['SMA_50_slope', 'Relative_Volume', 'RSI', 'MACD', 'regime', 'ATR']
    test_vector = np.array([0.1, 1.5, 55.0, 0.05, 1.0, 2.5])
    
    print("\n--- Testing Similarity Search ---")
    similarity_forecast = get_similarity_forecast(test_vector)
    
    print("\n--- Test Result ---")
    print(f"Similarity-weighted forecast (ŷ_sim): {similarity_forecast}")
    print("Note: This will be 0.0 if your Pinecone index is not yet populated.")
    print("-------------------")
    
if __name__ == "__main__":
    main()