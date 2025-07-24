import numpy as np

def f_symb(z):
    # Features: ['SMA_50_slope' 'Relative_Volume' 'RSI' 'MACD' 'regime' 'ATR' 'T10Y2Y'
 'UNRATE' 'UMCSENT' 'VIXCLS' 'news_sentiment' 'analyst_buy_rating'
 'analyst_hold_rating' 'analyst_sell_rating' 'analyst_rating_momentum']
    return z[10]/z[5]
