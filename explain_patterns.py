# explain_patterns.py

import json
import statistics
import config
import google.generativeai as genai
import pinecone
from tqdm import tqdm
import pandas as pd
import numpy as np

# --- THIS IS THE FIX: Import from our new utils.py file ---
from utils import add_features 
# ---------------------------------------------------------
from discovery_pipeline import fetch_polygon_data

# --- Initialization ---
genai.configure(api_key=config.GEMINI_API_KEY)
chat_model = genai.GenerativeModel('gemini-1.5-flash')
embedding_model = 'models/embedding-001'

pc = pinecone.Pinecone(api_key=config.PINECONE_API_KEY)
INDEX_NAME = "trade-signal-library"
index = pc.Index(INDEX_NAME)


def get_indicator_fingerprint(events, full_data):
    """
    Calculates the average indicator values for all events in a pattern cluster.
    """
    fingerprints = []
    for event_id in events:
        # The event ID is now just the string from the vetted_patterns file
        try:
            ticker, _, date_str = event_id.split('_', 2)
            date = pd.to_datetime(date_str)
            if ticker in full_data and date in full_data[ticker].index:
                fingerprints.append({
                    'ATR': full_data[ticker].loc[date, 'ATR'],
                    'VWAP': full_data[ticker].loc[date, 'VWAP'],
                    'SMA_50': full_data[ticker].loc[date, 'SMA_50'],
                })
        except ValueError:
            # Handle cases where the event_id format is different
            continue
    
    if not fingerprints:
        return {}

    avg_fingerprint = pd.DataFrame(fingerprints).mean().to_dict()
    return avg_fingerprint

def main():
    """
    Analyzes vetted patterns, generates statistical profiles and AI explanations,
    and indexes the final analysis in Pinecone.
    """
    try:
        with open('vetted_patterns.jsonl') as f:
            vetted_patterns = [json.loads(line) for line in f]
    except FileNotFoundError:
        print("Error: vetted_patterns.jsonl not found. Please run vetting_pipeline.py first.")
        return
        
    all_event_ids = [item for p in vetted_patterns for item in p['events']]
    all_tickers = set(p_id.split('_')[0] for p_id in all_event_ids)
    
    print("Fetching historical data for analysis...")
    full_data = {}
    for ticker in all_tickers:
        data = fetch_polygon_data(ticker)
        if data is not None:
            full_data[ticker] = add_features(data)

    print(f"\nFound {len(vetted_patterns)} vetted patterns to analyze and explain.")
    final_analysis_output = []

    for pattern in tqdm(vetted_patterns, desc="Generating Deep-Dive Analysis"):
        key = pattern['pattern_id']
        
        fingerprint = get_indicator_fingerprint(pattern['events'], full_data)
        fingerprint_text = ", ".join([f"{k}: {v:.2f}" for k, v in fingerprint.items()])

        prompt = (
            f"You are a quantitative financial analyst. A new trading pattern named '{key}' has been discovered and validated.\n"
            f"Here is its statistical profile:\n"
            f"- Historical Up Rate (Win Rate): {pattern['up_rate']:.1%}\n"
            f"- Historical Down Rate (Loss Rate): {pattern['down_rate']:.1%}\n"
            f"- Sample Size: {pattern['sample_size']} occurrences.\n"
            f"- Average Indicator 'Fingerprint': {fingerprint_text}\n\n"
            "Based on all this information, please return a JSON object with three keys:\n"
            "1. 'pattern_name': A short, professional, and descriptive name for this pattern.\n"
            "2. 'statistical_summary': A one-paragraph summary of the pattern's historical performance and reliability.\n"
            "3. 'economic_rationale': A one-paragraph explanation of the likely economic or market dynamic this pattern represents. Why might it be a valid, non-random signal?"
        )
        
        try:
            response = chat_model.generate_content(prompt)
            cleaned_text = response.text.replace('```json', '').replace('```', '').strip()
            result = json.loads(cleaned_text)
            name = result.get('pattern_name', key)
            summary = result.get('statistical_summary', "Summary not available.")
            rationale = result.get('economic_rationale', "Rationale not available.")
        except Exception as e:
            print(f"\nCould not parse AI response for {key}, using fallback. Error: {e}")
            name, summary, rationale = key, "Could not generate summary.", "Could not generate rationale."

        dossier = (
            f"Pattern Name: {name}\n"
            f"Internal ID: {key}\n"
            f"--- Performance ---\n"
            f"Up Rate: {pattern['up_rate']:.1%}\n"
            f"Down Rate: {pattern['down_rate']:.1%}\n"
            f"Sample Size: {pattern['sample_size']} occurrences\n"
            f"--- AI Analysis ---\n"
            f"Statistical Summary: {summary}\n"
            f"Economic Rationale: {rationale}"
        )

        embedding = genai.embed_content(model=embedding_model, content=dossier, task_type="RETRIEVAL_DOCUMENT")["embedding"]
        index.upsert(
            vectors=[{'id': key, 'values': embedding, 'metadata': {'dossier': dossier}}],
            namespace='vetted-patterns'
        )

        final_analysis_output.append({
            'pattern_id': key, 'pattern_name': name, 'up_rate': pattern['up_rate'],
            'down_rate': pattern['down_rate'], 'statistical_summary': summary,
            'economic_rationale': rationale, 'dossier': dossier
        })

    output_file = 'final_analysis.jsonl'
    with open(output_file, 'w') as f:
        for item in final_analysis_output:
            f.write(json.dumps(item) + '\n')
            
    print(f"\nDeep analysis complete. Final results saved to {output_file} and indexed in Pinecone.")

if __name__ == "__main__":
    main()