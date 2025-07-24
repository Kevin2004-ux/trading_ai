# data_ingest/alternative_data.py

import os
import requests
import numpy as np
from textblob import TextBlob
from dotenv import load_dotenv

load_dotenv(override=True)

def fetch_stock_news(ticker: str, limit: int = 20) -> list:
    """
    Fetches a list of recent news article headlines and descriptions for a ticker.
    """
    print(f"--- Fetching recent news for {ticker.upper()} ---")
    api_key = os.getenv("POLYGON_API_KEY")
    if not api_key:
        raise ValueError("POLYGON_API_KEY not found in .env file")

    url = f"https://api.polygon.io/v2/reference/news?ticker={ticker.upper()}&limit={limit}"

    try:
        response = requests.get(url, headers={"Authorization": f"Bearer {api_key}"})
        response.raise_for_status()
        articles = response.json().get('results', [])
        # Combine title and description for better context
        return [f"{article.get('title', '')}. {article.get('description', '')}" for article in articles]
    except requests.exceptions.RequestException as e:
        print(f"Error fetching news: {e}")
        return []

def analyze_sentiment(text: str) -> float:
    """
    Analyzes a piece of text and returns its sentiment polarity.
    - Polarity is a float between -1.0 (very negative) and 1.0 (very positive).
    """
    analysis = TextBlob(text)
    return analysis.sentiment.polarity

def get_average_sentiment(ticker: str) -> float:
    """
    Fetches the latest news for a ticker and calculates the average
    sentiment score of all articles.
    """
    articles = fetch_stock_news(ticker)
    if not articles:
        return 0.0 # Return neutral if no news

    sentiment_scores = [analyze_sentiment(article) for article in articles]

    avg_score = np.mean(sentiment_scores)
    print(f"✅ Average sentiment score for {ticker}: {avg_score:.4f}")
    return avg_score


if __name__ == "__main__":
    # Test the functions with a ticker
    get_average_sentiment("TSLA")