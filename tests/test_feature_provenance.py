from features import (
    FeatureProvenance,
    build_core_market_feature_provenance,
    summarize_feature_provenance,
)
from scanner.swing_scanner import build_stock_candidate, scan_swing_candidates


def _market_snapshot(ticker: str = "AAPL", *, relative_volume=1.8) -> dict:
    return {
        "ok": True,
        "ticker": ticker,
        "source": "polygon",
        "timestamp": "2026-06-05T12:00:00+00:00",
        "error": None,
        "data": {
            "quote": {
                "last_price": 120.0,
                "previous_close": 118.0,
                "day_volume": 2_000_000,
                "last_trade_timestamp": "2026-06-05T12:00:00+00:00",
            },
            "quote_status": "available",
            "technical_snapshot": {
                "ok": True,
                "error": None,
                "current_price": 120.0,
                "sma_20": 114.0,
                "sma_50": 105.0,
                "sma_200": 100.0,
                "average_volume_20": 2_000_000,
                "relative_volume": relative_volume,
                "atr_14": 4.0,
                "atr_percent": 3.33,
                "high_20": 121.0,
            },
            "data_freshness": {
                "ok": True,
                "latest_bar_timestamp": "2026-06-05T00:00:00+00:00",
                "is_stale": False,
                "freshness_label": "fresh",
                "warnings": [],
            },
            "data_quality": {
                "ok": True,
                "quality_label": "good",
                "price_source": "polygon",
                "quote_status": "available",
                "final_recommendation_allowed": True,
                "warnings": [],
                "errors": [],
            },
        },
    }


def test_feature_provenance_model_serializes_compactly():
    row = FeatureProvenance(
        feature_name="current_price",
        feature_value_available=True,
        provider="polygon",
        source="quote.last_price",
        as_of="2026-06-05T12:00:00+00:00",
        confidence="high",
        allowed_for_recommendation=True,
        allowed_for_research_only=True,
        raw_metadata={"nested": {"safe": True}},
    )

    payload = row.to_dict()
    compact = row.compact()

    assert payload["feature_name"] == "current_price"
    assert payload["raw_metadata"]["nested"]["safe"] is True
    assert compact["allowed_for_recommendation"] is True
    assert compact["provider"] == "polygon"


def test_core_market_feature_provenance_marks_safe_features_recommendation_allowed():
    provenance = build_core_market_feature_provenance("AAPL", _market_snapshot())
    summary = summarize_feature_provenance(provenance)

    assert provenance["current_price"]["feature_value_available"] is True
    assert provenance["current_price"]["allowed_for_recommendation"] is True
    assert provenance["relative_volume"]["provider"] == "polygon"
    assert summary["feature_count"] >= 6
    assert summary["unsafe_features"] == []


def test_build_stock_candidate_attaches_feature_provenance():
    candidate = build_stock_candidate("AAPL", _market_snapshot())

    assert "feature_provenance" in candidate
    assert candidate["feature_provenance"]["current_price"]["source"] == "quote.last_price"
    assert candidate["feature_provenance_summary"]["allowed_for_recommendation_count"] > 0


def test_missing_unsafe_provenance_does_not_create_paper_eligibility(monkeypatch, tmp_path):
    snapshot = _market_snapshot("WEAK", relative_volume=None)
    monkeypatch.setattr("scanner.swing_scanner.get_market_snapshot", lambda ticker, lookback_days=180: snapshot)

    result = scan_swing_candidates(["WEAK"], db_path=str(tmp_path / "provenance.db"))

    assert result["total_passed"] == 0
    assert result["total_rejected"] == 1
    rejected = result["rejected_candidates"][0]
    assert rejected["feature_provenance"]["relative_volume"]["allowed_for_recommendation"] is False
    assert rejected["recommendation_status"] == "rejected"
