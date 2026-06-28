from __future__ import annotations

from collections import defaultdict
from typing import Any

from scanner.universe_builder import get_default_universe

from .source_models import DiscoveryCandidate


DEFAULT_FALLBACK_UNIVERSES = ["active", "large_cap", "tech", "growth"]


def discover_liquid_fallback_candidates(
    *,
    max_tickers: int,
    discovered_at: str,
    universes: list[str] | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    requested = universes or DEFAULT_FALLBACK_UNIVERSES
    warnings: list[str] = []
    memberships: dict[str, list[str]] = defaultdict(list)

    for universe in requested:
        loaded = get_default_universe(str(universe), max_tickers=max(max_tickers * 3, max_tickers))
        if not loaded.get("ok"):
            warnings.extend(str(item) for item in loaded.get("errors", []) if item)
            continue
        for ticker in loaded.get("tickers", []):
            normalized = str(ticker or "").strip().upper()
            if normalized and str(universe) not in memberships[normalized]:
                memberships[normalized].append(str(universe))

    rows: list[DiscoveryCandidate] = []
    for ticker, ticker_universes in memberships.items():
        first_priority = min(requested.index(source) for source in ticker_universes if source in requested)
        membership_score = len(ticker_universes) * 7.5
        priority_score = max(0.0, 12.0 - (first_priority * 3.0))
        score = min(78.0, 42.0 + membership_score + priority_score)
        rows.append(
            DiscoveryCandidate(
                ticker=ticker,
                source=",".join(ticker_universes),
                source_type="liquid_fallback",
                discovered_at=discovered_at,
                as_of=discovered_at,
                discovery_score=score,
                reasons=[f"Curated liquid fallback membership: {', '.join(ticker_universes)}."],
                raw_metadata={
                    "universes": ticker_universes,
                    "membership_count": len(ticker_universes),
                    "source_priority": first_priority,
                },
                point_in_time_safe=True,
                requires_live_validation=True,
            )
        )

    ranked = sorted(rows, key=lambda candidate: (-candidate.discovery_score, candidate.ticker))
    return [candidate.to_dict() for candidate in ranked[:max_tickers]], warnings
