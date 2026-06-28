import config

from providers.capabilities import (
    ProviderCapability,
    configured_provider_capabilities,
    summarize_provider_capabilities,
)


def test_provider_capability_model_serializes():
    capability = ProviderCapability(
        provider_name="ibkr",
        provider_type="market_data",
        available=True,
        authenticated=True,
        entitlement_status="available",
        supports_realtime_quotes=True,
        supports_historical_bars=True,
        warnings=["delayed data"],
    )

    payload = capability.to_dict()
    compact = capability.compact()

    assert payload["provider_name"] == "ibkr"
    assert compact["supports_historical_bars"] is True
    assert compact["warnings"] == ["delayed data"]


def test_configured_provider_capabilities_are_defensive(monkeypatch):
    monkeypatch.setenv("MARKET_DATA_PROVIDER", "polygon")
    monkeypatch.setenv("OPTIONS_DATA_PROVIDER", "polygon")
    monkeypatch.setattr(config, "POLYGON_API_KEY", "", raising=False)

    capabilities = configured_provider_capabilities()

    assert len(capabilities) == 2
    assert capabilities[0]["provider_name"] == "polygon"
    assert capabilities[0]["available"] is False
    assert capabilities[0]["degraded"] is True
    assert capabilities[0]["warnings"]


def test_provider_capability_summary_from_feature_provenance():
    payload = {
        "candidate": {
            "feature_provenance": {
                "current_price": {
                    "feature_name": "current_price",
                    "feature_value_available": True,
                    "provider": "ibkr",
                    "provider_type": "market_data",
                    "source": "quote.last_price",
                    "allowed_for_recommendation": True,
                    "warnings": [],
                    "errors": [],
                },
                "sma_20": {
                    "feature_name": "sma_20",
                    "feature_value_available": True,
                    "provider": "ibkr",
                    "provider_type": "market_data",
                    "source": "technical_snapshot",
                    "allowed_for_recommendation": True,
                    "warnings": [],
                    "errors": [],
                },
            }
        }
    }

    capabilities = summarize_provider_capabilities(payload, fallback_to_configured=False)

    assert capabilities[0]["provider_name"] == "ibkr"
    assert capabilities[0]["available"] is True
    assert capabilities[0]["supports_realtime_quotes"] is True
    assert capabilities[0]["supports_historical_bars"] is True


def test_unknown_degraded_provider_capability_does_not_crash():
    capabilities = summarize_provider_capabilities(
        {
            "feature_provenance": {
                "current_price": {
                    "feature_name": "current_price",
                    "feature_value_available": False,
                    "provider": "mystery_feed",
                    "provider_type": "market_data",
                    "source": "unknown",
                    "allowed_for_recommendation": False,
                    "warnings": ["feature missing"],
                    "errors": ["provider unavailable"],
                }
            }
        },
        fallback_to_configured=False,
    )

    assert capabilities[0]["provider_name"] == "mystery_feed"
    assert capabilities[0]["available"] is False
    assert capabilities[0]["degraded"] is True
    assert capabilities[0]["errors"] == ["provider unavailable"]
