import numpy as np

# This would be in a shared utility or config file
SECTOR_MAPPING = {
    'AAPL': 'Technology', 'TSLA': 'Consumer Discretionary', 'NVDA': 'Technology',
    'MSFT': 'Technology', 'GOOGL': 'Communication Services', 'JPM': 'Financials'
}

def get_sector(ticker):
    """Returns the sector for a given stock ticker."""
    return SECTOR_MAPPING.get(ticker, 'Other')

def apply_risk_management(options_list, latest_data, portfolio_state, aggressiveness="balanced"):
    """Applies both trade-level and portfolio-level risk rules, now using aggressiveness."""
    if not options_list:
        return []
    
    print(f"  Applying portfolio-aware risk management with '{aggressiveness}' profile...")

    ticker = latest_data['ticker']
    current_price = latest_data['Close']
    atr = latest_data.get('ATR', current_price * 0.02)
    if atr == 0: atr = current_price * 0.02

    # Define risk levels based on the aggressiveness setting
    risk_factors = {
        "conservative": 0.005, # Risk 0.5% of total portfolio value
        "balanced": 0.01,       # Risk 1.0%
        "aggressive": 0.025      # Risk 2.5%
    }
    risk_percentage = risk_factors.get(aggressiveness, 0.01)

    # --- Rule 1: Dynamic Risk Budget ---
    risk_budget_per_trade = portfolio_state['total_value'] * risk_percentage
    position_size_shares = risk_budget_per_trade / atr
    
    # --- Rule 2: Portfolio Concentration Limit ---
    max_position_notional = portfolio_state['total_value'] * 0.20
    if (position_size_shares * current_price) > max_position_notional:
        print(f"  RISK CHECK: Concentration limit hit. Reducing size for {ticker}.")
        position_size_shares = max_position_notional / current_price

    # --- Rule 3: Sector Exposure Limit ---
    ticker_sector = get_sector(ticker)
    current_sector_exposure = portfolio_state['sector_exposure'].get(ticker_sector, 0.0)
    proposed_notional_add = position_size_shares * current_price
    max_sector_exposure = portfolio_state['total_value'] * 0.40

    if (current_sector_exposure + proposed_notional_add) > max_sector_exposure:
        print(f"  RISK CHECK: Sector limit for '{ticker_sector}' hit. Trade for {ticker} rejected.")
        return []

    # If all checks pass, apply the final sizing
    sized_options = []
    for option in options_list:
        option['recommended_shares'] = round(position_size_shares)
        option['notional_value'] = round(position_size_shares * current_price, 2)
        sized_options.append(option)
        
    print("  All risk checks passed. Position sized.")
    return sized_options