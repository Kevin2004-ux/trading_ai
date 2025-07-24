# data_ingest/tests/test_clients.py

import pytest
import pandas as pd
from datetime import datetime
from data_ingest.clients import PolygonClient

# This is our "mock" data, a sample of what the real Polygon API would return.
MOCK_API_RESPONSE = {
    "results": [
        {
            "t": 1704171600000, "o": 187.14, "h": 188.44, "l": 183.79, "c": 184.25, "v": 102550189
        },
        {
            "t": 1704258000000, "o": 182.15, "h": 182.76, "l": 180.17, "c": 181.91, "v": 80720499
        }
    ]
}

def test_polygon_client_get_historical_success(mocker):
    """
    Tests that the PolygonClient correctly processes a successful API response.
    """
    # Arrange: Set up the "mock" for the requests.get call
    mock_response = mocker.Mock()
    mock_response.json.return_value = MOCK_API_RESPONSE
    mock_response.raise_for_status.return_value = None
    mocker.patch("requests.get", return_value=mock_response)

    # Act: Call the method we want to test
    client = PolygonClient(api_key="fake_key")
    start_date = datetime(2024, 1, 1)
    end_date = datetime(2024, 1, 3)
    result_df = client.get_historical("AAPL", start_date, end_date)

    # Assert: Check that the result is what we expect
    assert isinstance(result_df, pd.DataFrame)
    assert not result_df.empty
    assert len(result_df) == 2
    assert 'close' in result_df.columns
    assert result_df.index.name == 'date'# data_ingest/tests/test_clients.py

import pytest
import pandas as pd
from datetime import datetime
import requests
from data_ingest.clients import PolygonClient

# This is our "mock" data, a sample of what the real Polygon API would return.
MOCK_API_RESPONSE = {
    "results": [
        {
            "t": 1704171600000, "o": 187.14, "h": 188.44, "l": 183.79, "c": 184.25, "v": 102550189
        },
        {
            "t": 1704258000000, "o": 182.15, "h": 182.76, "l": 180.17, "c": 181.91, "v": 80720499
        }
    ]
}

def test_polygon_client_get_historical_success(mocker):
    """
    Tests that the PolygonClient correctly processes a successful API response.
    """
    # Arrange: Set up the "mock" for the requests.get call
    mock_response = mocker.Mock()
    mock_response.json.return_value = MOCK_API_RESPONSE
    mock_response.raise_for_status.return_value = None
    mocker.patch("requests.get", return_value=mock_response)

    # Act: Call the method we want to test
    client = PolygonClient(api_key="fake_key")
    start_date = datetime(2024, 1, 1)
    end_date = datetime(2024, 1, 3)
    result_df = client.get_historical("AAPL", start_date, end_date)

    # Assert: Check that the result is what we expect
    assert isinstance(result_df, pd.DataFrame)
    assert not result_df.empty
    assert len(result_df) == 2
    assert 'close' in result_df.columns
    assert result_df.index.name == 'date'

def test_polygon_client_get_historical_api_error(mocker):
    """
    Tests that the PolygonClient returns an empty DataFrame when the API
    call fails.
    """
    # Arrange: Set up a mock that simulates an HTTP error.
    mocker.patch("requests.get", side_effect=requests.exceptions.RequestException("API Error"))

    # Act: Call the method we want to test.
    client = PolygonClient(api_key="fake_key")
    start_date = datetime(2024, 1, 1)
    end_date = datetime(2024, 1, 3)
    result_df = client.get_historical("AAPL", start_date, end_date)

    # Assert: Check that the result is an empty DataFrame.
    assert isinstance(result_df, pd.DataFrame)
    assert result_df.empty