# data_ingest/clients.py

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Callable, Optional
import pandas as pd
import os
import requests
import time
from dotenv import load_dotenv
from ib_insync import IB, Stock, util


# --- Abstract Base Classes (The "Blueprints") ---

class MarketDataClient(ABC):
    """
    An abstract interface for clients that provide equity market data,
    both historical and live.
    """
    @abstractmethod
    def get_historical(self, ticker: str, start: datetime, end: datetime) -> pd.DataFrame:
        """Fetches historical OHLCV data for a given ticker."""
        ...

    @abstractmethod
    def stream_live(self, ticker: str, on_update: Callable[[dict], None]) -> None:
        """Streams live tick or bar data for a given ticker."""
        ...


class OptionsClient(ABC):
    """
    An abstract interface for clients that provide full option chain data.
    """
    @abstractmethod
    def get_option_chain(self, ticker: str, as_of: datetime) -> pd.DataFrame:
        """Fetches the entire option chain for a ticker on a specific date."""
        ...


# --- Concrete Implementations ---

class PolygonClient(MarketDataClient):
    """A client for fetching historical equity data from Polygon.io."""

    def __init__(self, api_key: Optional[str] = None):
        """
        Initializes the client.
        API key is read from a .env file or environment variables.
        """
        load_dotenv()
        
        self.api_key = api_key or os.getenv("POLYGON_API_KEY")
        if not self.api_key:
            raise ValueError("Polygon API key not found. Please set it in your .env file or as an environment variable.")
        self.base_url = "https://api.polygon.io"

    def get_historical(self, ticker: str, start: datetime, end: datetime) -> pd.DataFrame:
        """
        Fetches historical OHLCV bars from the Polygon.io Aggregates API.
        """
        print(f"Fetching {ticker} data from {start.strftime('%Y-%m-%d')} to {end.strftime('%Y-%m-%d')}...")
        
        start_str = start.strftime('%Y-%m-%d')
        end_str = end.strftime('%Y-%m-%d')
        
        url = (
            f"{self.base_url}/v2/aggs/ticker/{ticker.upper()}/range/1/day/{start_str}/{end_str}"
            f"?adjusted=true&sort=asc&limit=50000"
        )

        try:
            response = requests.get(url, headers={"Authorization": f"Bearer {self.api_key}"})
            response.raise_for_status()
            
            data = response.json().get('results', [])
            if not data:
                print(f"Warning: No data found for {ticker} in the given date range.")
                return pd.DataFrame()

            df = pd.DataFrame(data)
            
            df = df.rename(columns={
                't': 'timestamp', 'o': 'open', 'h': 'high', 
                'l': 'low', 'c': 'close', 'v': 'volume'
            })
            
            df['date'] = pd.to_datetime(df['timestamp'], unit='ms').dt.date
            df = df.set_index('date')
            
            return df[['open', 'high', 'low', 'close', 'volume']]

        except requests.exceptions.RequestException as e:
            print(f"An error occurred while fetching data for {ticker}: {e}")
            return pd.DataFrame()

    def stream_live(self, ticker: str, on_update: Callable[[dict], None]) -> None:
        """
        (Placeholder) Live streaming for Polygon would be implemented here
        using their WebSocket APIs.
        """
        print("Live streaming is not yet implemented for PolygonClient.")
        ...

class PolygonOptionsClient(OptionsClient):
    """A client for fetching options chain data from Polygon.io."""

    def __init__(self, api_key: Optional[str] = None):
        """
        Initializes the client.
        API key is read from a .env file or environment variables.
        """
        load_dotenv()
        
        self.api_key = api_key or os.getenv("POLYGON_API_KEY")
        if not self.api_key:
            raise ValueError("Polygon API key not found. Please set it in your .env file or as an environment variable.")
        self.base_url = "https://api.polygon.io"

    def get_option_chain(self, ticker: str, as_of: Optional[datetime] = None) -> pd.DataFrame:
        """
        Fetches the full option chain for a given underlying ticker.
        Handles pagination and rate limiting to retrieve all contracts.
        """
        print(f"Fetching option chain for {ticker.upper()}...")
        
        all_contracts = []
        url = f"{self.base_url}/v3/reference/options/contracts?underlying_ticker={ticker.upper()}&limit=1000"
        
        while url:
            try:
                response = requests.get(url, headers={"Authorization": f"Bearer {self.api_key}"})
                response.raise_for_status()
                
                data = response.json()
                all_contracts.extend(data.get('results', []))
                
                url = data.get('next_url')

                # If there's a next page, wait 12 seconds to respect the 5 requests/minute limit
                if url:
                    print("Rate limit: sleeping for 12 seconds before next page...")
                    time.sleep(12)

            except requests.exceptions.RequestException as e:
                print(f"An error occurred while fetching the option chain for {ticker}: {e}")
                return pd.DataFrame()
                
        if not all_contracts:
            print(f"Warning: No option contracts found for {ticker}.")
            return pd.DataFrame()
            
        return pd.DataFrame(all_contracts)

class IBKRClient(MarketDataClient):
    """
    A client for fetching live and historical data from Interactive Brokers.
    """
    def __init__(self, host='127.0.0.1', port=5000, client_id=1):
        """Initializes and connects to the TWS or Gateway application."""
        self.ib = IB()
        try:
            print(f"Connecting to IBKR TWS/Gateway at {host}:{port}...")
            self.ib.connect(host, port, clientId=client_id, readonly=True)
            print("✅ Successfully connected to IBKR.")
        except Exception as e:
            print(f"❌ Connection to IBKR failed: {e}")
            print("Please ensure TWS or IB Gateway is running and API connections are enabled.")

    def get_historical(self, ticker: str, start: datetime, end: datetime) -> pd.DataFrame:
        """
        (Placeholder) Fetches historical data from IBKR.
        """
        print("IBKR get_historical not yet implemented.")
        return pd.DataFrame()

    def stream_live(self, ticker: str, on_update: Callable[[dict], None]) -> None:
        """
        (Placeholder) Subscribes to live market data for a ticker.
        This requires an event loop to run continuously.
        """
        print("IBKR stream_live not yet implemented.")
        pass