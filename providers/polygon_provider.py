from __future__ import annotations


SOURCE_MARKET_DATA = "polygon"
SOURCE_OPTIONS_DATA = "polygon_options"


def get_polygon_provider_status() -> dict:
    return {
        "market_data_provider": SOURCE_MARKET_DATA,
        "options_data_provider": SOURCE_OPTIONS_DATA,
    }

