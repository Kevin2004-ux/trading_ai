# tools/get_prediction_dossier.py
    
import torch
from datetime import datetime, timedelta
import sys
sys.path.append('.')
    
from modeling.swing_policy import SwingTradePolicy
from data_ingest import PolygonClient
from feature_store.features import calculate_technical_features
from modeling.similarity_search import find_similar_patterns
from data_ingest.alternative_data import get_average_sentiment
from modeling.market_impact import calculate_market_impact_score
from tools.strategy_lookup import get_best_strategy_for_regime
from modeling.regime import RegimeDetector

# Define the exact feature list the v4 model was trained on
V4_FEATURE_LIST = ['sma_50', 'rsi', 'macd', 'similarity_score', 'sentiment_score', 'relative_volume']
MODEL_PATH = "swing_trade_model_v4.pth"

# Create a model instance with the correct (6-feature) architecture
model = SwingTradePolicy(feature_list=V4_FEATURE_LIST)
# Load the saved weights into the correctly shaped model
model.load_state_dict(torch.load(MODEL_PATH))
model.eval()
    
def get_prediction_dossier(ticker: str) -> dict:
    client = PolygonClient()
    # Fetch a longer history for more stable HMM fitting
    ohlcv_df = client.get_historical(ticker, datetime.now() - timedelta(days=365), datetime.now())
    if ohlcv_df.empty: return {"error": f"Could not fetch historical data for {ticker}."}
    
    # 1. Determine the CURRENT Market Regime
    regime_detector = RegimeDetector(n_regimes=3)
    regime_detector.fit(ohlcv_df)
    current_regime = int(regime_detector.predict(ohlcv_df).iloc[-1])
    
    # 2. Look up the Best Strategy for this Regime
    best_strategy = get_best_strategy_for_regime(current_regime)

    # 3. Calculate all other features
    features_df = calculate_technical_features(ohlcv_df)
    if features_df.empty: return {"error": "Could not calculate technical features."}
    latest_features = features_df.iloc[-1]
    
    pinecone_features = latest_features[['sma_50', 'rsi', 'macd']].values.tolist()
    similarity_score, _ = find_similar_patterns(pinecone_features)
    sentiment_score = get_average_sentiment(ticker)
    market_impact_score = calculate_market_impact_score(features_df)

    # --- CORRECTED FEATURE ASSEMBLY ---
    # 4. Manually assemble the feature vector in the correct order
    final_feature_vector = [
        latest_features['sma_50'],
        latest_features['rsi'],
        latest_features['macd'],
        similarity_score,
        sentiment_score,
        latest_features['relative_volume']
    ]
    # --- END CORRECTION ---

    feature_tensor = torch.tensor(final_feature_vector).float().unsqueeze(0)
    decision_index = model.predict(feature_tensor)
    action_map = {0: "SELL", 1: "HOLD", 2: "BUY"}

    # 5. Assemble the Final Dossier
    dossier = {
        "ticker": ticker.upper(),
        "current_market_regime": current_regime,
        "retrieved_strategy": best_strategy,
        "core_model_decision": action_map.get(decision_index, "UNKNOWN"),
        "key_technical_features": {"rsi": round(latest_features['rsi'], 2), "macd": round(latest_features['macd'], 2), "relative_volume": round(latest_features['relative_volume'], 2)},
        "historical_pattern_analysis": {"similarity_score": round(similarity_score, 4), "notes": "Positive score suggests similar past patterns were bullish." if similarity_score > 0 else "Negative score suggests similar past patterns were bearish."},
        "news_sentiment_analysis": {"score": round(sentiment_score, 4), "summary": "Positive" if sentiment_score > 0.05 else "Negative" if sentiment_score < -0.05 else "Neutral"},
        "game_theory_analysis": {"market_impact_score": round(market_impact_score, 4), "notes": "Score near 0 means average market attention. Score near -1 means trade may be overly crowded."}
    }
    return dossier