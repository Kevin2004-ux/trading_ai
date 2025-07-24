# realtime/market_impact_model.py
import numpy as np

def adjust_with_market_impact(y_raw, relative_volume, k):
    """
    Adjusts a raw forecast based on relative volume.
    High volume suggests a move is already underway, reducing potential.
    
    Args:
        y_raw (float): The raw model forecast.
        relative_volume (float): The ratio of current volume to its moving average.
        k (float): The learned "crowdedness" parameter from walk-forward optimization.
    
    Returns:
        float: The adjusted forecast.
    """
    # The adjustment factor decays exponentially as volume increases
    adjustment_factor = np.exp(-k * (relative_volume - 1.0))
    
    # Ensure the factor doesn't amplify the signal, only attenuates it
    adjustment_factor = min(adjustment_factor, 1.0)

    return y_raw * adjustment_factor