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