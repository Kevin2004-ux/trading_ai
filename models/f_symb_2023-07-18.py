import numpy as np

def f_symb(z):
    # Features: ['SMA_50_slope' 'Relative_Volume' 'RSI' 'MACD' 'regime' 'ATR' 'T10Y2Y'
 'UNRATE' 'UMCSENT' 'VIXCLS' 'news_sentiment' 'analyst_buy_rating'
 'analyst_hold_rating' 'analyst_sell_rating' 'analyst_rating_momentum']
    return 0.021054346*z[3]/z[2] + 0.039916422
