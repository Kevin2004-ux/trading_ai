import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# ==============================================================================
# -- API CREDENTIALS --
# This section securely reads your keys from the private .env file.
# The actual keys are NOT here.
# ==============================================================================
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
POLYGON_API_KEY = os.getenv("POLYGON_API_KEY")
PINECONE_API_KEY = os.getenv("PINECONE_API_KEY")
PINECONE_ENVIRONMENT = os.getenv("PINECONE_ENVIRONMENT")
FMP_API_KEY = os.getenv("FMP_API_KEY")
MARKET_DATA_PROVIDER = os.getenv("MARKET_DATA_PROVIDER", "polygon")
OPTIONS_DATA_PROVIDER = os.getenv("OPTIONS_DATA_PROVIDER", "polygon")
IBKR_HOST = os.getenv("IBKR_HOST", "127.0.0.1")
IBKR_PORT = os.getenv("IBKR_PORT", "7496")
IBKR_CLIENT_ID = os.getenv("IBKR_CLIENT_ID", "123")
IBKR_READ_ONLY = os.getenv("IBKR_READ_ONLY", "true")
IBKR_USE_DELAYED_DATA = os.getenv("IBKR_USE_DELAYED_DATA", "true")
IBKR_TIMEOUT_SECONDS = os.getenv("IBKR_TIMEOUT_SECONDS", "10")
MARKET_DATA_MODE = os.getenv("MARKET_DATA_MODE", "auto")
ALLOW_HISTORICAL_BAR_FALLBACK = os.getenv("ALLOW_HISTORICAL_BAR_FALLBACK", "true")
ALLOW_LIVE_QUOTE_REQUIRED = os.getenv("ALLOW_LIVE_QUOTE_REQUIRED", "false")
ALLOW_OPTIONS_WITHOUT_QUOTES = os.getenv("ALLOW_OPTIONS_WITHOUT_QUOTES", "false")

# ==============================================================================
# -- TRADING & DATA PARAMETERS --
# ==============================================================================
# List of stock tickers to monitor and analyze
STOCKS_TO_MONITOR = ['AAPL', 'TSLA', 'NVDA']


# ==============================================================================
# -- BACKTESTING & WALK-FORWARD CONFIGURATION --
# ==============================================================================
# These parameters control the walk-forward validation, ensuring we avoid lookahead bias.
# Example: Train on 3 years, validate on the next 1 year, then test on the following 1 year.
TRAIN_YEARS = 1
VALIDATION_YEARS = 1
VALIDATION_MONTHS = int(os.getenv("VALIDATION_MONTHS", "12"))
TEST_YEARS = 0
# This controls how often the entire model suite is retrained.
ROLLING_WINDOW_STEP_MONTHS = 6


# ==============================================================================
# -- REALISTIC COST CONFIGURATION --
# ==============================================================================
# These values make our backtest results more realistic by accounting for trading frictions.
COMMISSION_PER_SHARE = 0.005  # Example cost per share traded
SLIPPAGE_PERCENT = 0.0005     # Simulates a 0.05% price slippage on trade execution


# ==============================================================================
# -- MODEL HYPERPARAMETERS --
# ==============================================================================
# A central place to tune the performance of our AI models.
NEURAL_NET_EPOCHS = 100
PYSR_ITERATIONS = 50
