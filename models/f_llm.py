import numpy as np

import numpy as np
import math

def f_llm(z):
    # z[0]=SMA_50_slope, z[1]=Relative_Volume, etc.
    macd_scaled = z[3] / (1 + np.abs(z[7])) #Scale MACD by unemployment rate
    rsi_vix_interaction = z[2] * (1 + 0.5 * z[9]) # RSI amplified by VIX
    atr_weight = 1 / (1 + z[5]) # ATR acts as a dampener, higher ATR lower weight

    numerator = np.sin( (-2.0 * macd_scaled + z[9]) / (macd_scaled + rsi_vix_interaction ))
    denominator = z[9] + 0.1 * z[1] #add a small relative volume component to denominator

    if denominator == 0: #Avoid division by zero error
        return 0

    return (numerator + 0.2 * atr_weight) / denominator