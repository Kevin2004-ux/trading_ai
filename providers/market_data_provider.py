from __future__ import annotations

import os

import config


DEFAULT_MARKET_DATA_PROVIDER = "polygon"
SUPPORTED_MARKET_DATA_PROVIDERS = {"polygon", "ibkr"}


def get_selected_market_data_provider() -> str:
    provider = (
        os.getenv("MARKET_DATA_PROVIDER")
        or getattr(config, "MARKET_DATA_PROVIDER", None)
        or DEFAULT_MARKET_DATA_PROVIDER
    )
    normalized = str(provider).strip().lower()
    return normalized if normalized in SUPPORTED_MARKET_DATA_PROVIDERS else DEFAULT_MARKET_DATA_PROVIDER


def is_ibkr_market_data_provider() -> bool:
    return get_selected_market_data_provider() == "ibkr"

