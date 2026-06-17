from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def simulate_provider_outage(
    tickers: list[str],
    provider: str = "ibkr",
    config: dict | None = None,
) -> dict:
    normalized = [str(ticker).upper() for ticker in tickers or [] if ticker]
    return {
        "ok": True,
        "scenario": "provider_outage",
        "provider": provider,
        "timestamp": _now_iso(),
        "tickers": normalized,
        "data_quality": {
            "ok": False,
            "quality_label": "unavailable",
            "final_recommendation_allowed": False,
            "provider_status": "unavailable",
            "warnings": [f"{provider} provider outage simulated."],
            "errors": ["Market data provider unavailable under simulated outage."],
        },
        "warnings": ["Provider outage simulation returned degraded/unavailable data."],
        "errors": [],
    }


def simulate_stale_data(
    market_snapshot: dict,
    stale_days: int = 5,
    config: dict | None = None,
) -> dict:
    snapshot = deepcopy(market_snapshot) if isinstance(market_snapshot, dict) else {}
    stale_timestamp = (datetime.now(timezone.utc) - timedelta(days=max(int(stale_days), 0))).isoformat()
    snapshot.setdefault("data", {})["freshness"] = {
        "latest_bar_timestamp": stale_timestamp,
        "age_days": stale_days,
        "is_stale": True,
        "freshness_label": "stale",
    }
    snapshot["ok"] = False
    snapshot["error"] = f"Simulated stale market data: {stale_days} days old."
    return {
        "ok": True,
        "scenario": "bad_data_stale_prices",
        "market_snapshot": snapshot,
        "data_quality": {
            "ok": False,
            "quality_label": "stale",
            "final_recommendation_allowed": False,
            "warnings": [f"Market data is {stale_days} day(s) old."],
            "errors": ["Stale data blocks final paper recommendations."],
        },
        "warnings": ["Stale data simulation blocks final recommendations."],
        "errors": [],
    }


def simulate_partial_scan_timeout(
    scan_result: dict,
    timeout_fraction: float = 0.40,
    config: dict | None = None,
) -> dict:
    result = deepcopy(scan_result) if isinstance(scan_result, dict) else {}
    candidates = result.get("best_candidates") if isinstance(result.get("best_candidates"), list) else []
    timed_out_count = max(1, int(len(candidates) * max(0.0, min(float(timeout_fraction), 1.0)))) if candidates else 1
    result["ok"] = True
    result["scan_execution_summary"] = {
        **(result.get("scan_execution_summary") if isinstance(result.get("scan_execution_summary"), dict) else {}),
        "partial_results_used": True,
        "timeout_fraction": timeout_fraction,
        "timed_out_tickers": [f"SIM_TIMEOUT_{index + 1}" for index in range(timed_out_count)],
        "warnings": ["Simulated partial scan timeout; partial results preserved."],
    }
    return {
        "ok": True,
        "scenario": "partial_scan_timeout",
        "scan_result": result,
        "data_quality": {
            "ok": True,
            "quality_label": "usable_with_warnings",
            "final_recommendation_allowed": True,
            "warnings": ["Partial scan timeout simulated."],
            "errors": [],
        },
        "warnings": ["Partial scan timeout simulation preserved structured partial output."],
        "errors": [],
    }
