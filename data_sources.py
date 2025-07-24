import requests
import numpy as np
from textblob import TextBlob
import config

# --- News & Sentiment Functions ---

def fetch_stock_news(ticker, limit=20):
    """Fetches recent news articles for a given stock ticker from Polygon.io."""
    print(f"  Fetching news for {ticker}...")
    url = f"https://api.polygon.io/v2/reference/news?ticker={ticker}&limit={limit}&apiKey={config.POLYGON_API_KEY}"
    try:
        response = requests.get(url)
        response.raise_for_status()
        articles = response.json().get('results', [])
        # We only need the title and description for sentiment analysis
        return [f"{article['title']}. {article.get('description', '')}" for article in articles]
    except Exception as e:
        print(f"  Could not fetch news for {ticker}: {e}")
        return []

def get_sentiment_score(text):
    """Analyzes text and returns a sentiment polarity score."""
    analysis = TextBlob(text)
    # Polarity is a float between -1.0 (negative) and 1.0 (positive)
    return analysis.sentiment.polarity

def calculate_average_sentiment(ticker):
    """Fetches news, scores it, and returns the average sentiment score."""
    articles = fetch_stock_news(ticker)
    if not articles:
        return 0.0 # Return neutral if no news is found

    scores = [get_sentiment_score(article) for article in articles]
    return np.mean(scores)


# --- Expert Picks / Analyst Ratings Functions ---

def fetch_analyst_ratings(ticker):
    """Fetches the latest analyst ratings from Financial Modeling Prep."""
    print(f"  Fetching analyst ratings for {ticker}...")
    url = f"https://financialmodelingprep.com/api/v3/analyst-stock-recommendations/{ticker}?apikey={config.FMP_API_KEY}"
    try:
        response = requests.get(url)
        response.raise_for_status()
        # Return the list of recent ratings data
        return response.json()
    except Exception as e:
        print(f"  Could not fetch analyst ratings for {ticker}: {e}")
        return []

def process_ratings_to_features(ratings_data):
    """Processes raw ratings data into numerical features."""
    if not ratings_data:
        return {
            'analyst_buy_rating': 0,
            'analyst_hold_rating': 0,
            'analyst_sell_rating': 0,
            'analyst_rating_momentum': 0
        }

    # Focus on the most recent rating for momentum
    latest_rating = ratings_data[0]
    rating_map = {"strong buy": 2, "buy": 1, "hold": 0, "sell": -1, "strong sell": -2}

    return {
        'analyst_buy_rating': latest_rating.get('ratingScore', 0),
        'analyst_hold_rating': latest_rating.get('ratingDetailsHold', 0),
        'analyst_sell_rating': latest_rating.get('ratingDetailsSell', 0),
        'analyst_rating_momentum': rating_map.get(latest_rating.get('ratingRecommendation', '').lower(), 0)
    }