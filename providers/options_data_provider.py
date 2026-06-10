from __future__ import annotations

import os

import config


DEFAULT_OPTIONS_DATA_PROVIDER = "polygon"
SUPPORTED_OPTIONS_DATA_PROVIDERS = {"polygon", "ibkr"}


def get_selected_options_data_provider() -> str:
    provider = (
        os.getenv("OPTIONS_DATA_PROVIDER")
        or getattr(config, "OPTIONS_DATA_PROVIDER", None)
        or DEFAULT_OPTIONS_DATA_PROVIDER
    )
    normalized = str(provider).strip().lower()
    return normalized if normalized in SUPPORTED_OPTIONS_DATA_PROVIDERS else DEFAULT_OPTIONS_DATA_PROVIDER


def is_ibkr_options_data_provider() -> bool:
    return get_selected_options_data_provider() == "ibkr"

