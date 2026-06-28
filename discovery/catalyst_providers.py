from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import os
from typing import Any, Protocol

from scanner.universe_builder import validate_ticker_universe

from .catalyst_models import CatalystCandidate, CatalystDiscoveryRequest, CatalystProviderStatus, MAX_PROVIDER_SEED_TICKERS
from .source_models import safe_float, unique_texts


def _bool_env(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def _env_list(name: str) -> list[str]:
    return [item.strip() for item in str(os.getenv(name) or "").split(",") if item.strip()]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _as_dict(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list:
    return value if isinstance(value, list) else []


def _seed_tickers(request: CatalystDiscoveryRequest) -> list[str]:
    configured = _env_list("EXTERNAL_CATALYST_TICKERS")
    raw = configured or list(request.seed_tickers or [])
    validated = validate_ticker_universe(raw, max_tickers=MAX_PROVIDER_SEED_TICKERS)
    return list(validated.get("tickers", [])) if isinstance(validated, dict) and validated.get("ok") else []


class CatalystProvider(Protocol):
    name: str

    def status(self) -> CatalystProviderStatus:
        ...

    def discover(self, request: CatalystDiscoveryRequest) -> tuple[list[dict[str, Any]], CatalystProviderStatus]:
        ...


@dataclass
class StaticCatalystProvider:
    rows: list[dict[str, Any]]
    name: str = "static_test_catalyst"

    def status(self) -> CatalystProviderStatus:
        return CatalystProviderStatus(
            provider_name=self.name,
            configured=True,
            attempted=False,
            available=True,
        )

    def discover(self, request: CatalystDiscoveryRequest) -> tuple[list[dict[str, Any]], CatalystProviderStatus]:
        status = self.status()
        status.attempted = True
        candidates: list[dict[str, Any]] = []
        for row in self.rows:
            candidate = CatalystCandidate(
                ticker=str(row.get("ticker") or ""),
                source=str(row.get("source") or self.name),
                catalyst_type=str(row.get("catalyst_type") or "news"),
                title=str(row.get("title") or row.get("headline") or row.get("reason_discovered") or "Static catalyst candidate."),
                headline=row.get("headline"),
                url=row.get("url"),
                published_at=row.get("published_at"),
                discovered_at=request.discovered_at,
                as_of=str(row.get("as_of") or row.get("published_at") or request.discovered_at),
                discovery_score=safe_float(row.get("discovery_score"), 50.0),
                confidence=safe_float(row.get("confidence"), 0.7),
                reason_discovered=row.get("reason_discovered"),
                warnings=[str(item) for item in _as_list(row.get("warnings"))],
                errors=[str(item) for item in _as_list(row.get("errors"))],
                raw_metadata=_as_dict(row.get("raw_metadata")),
            )
            candidates.append(candidate.to_dict())
        status.available = bool(candidates)
        return candidates[: request.max_tickers], status


class FmpCatalystProvider:
    name = "fmp_catalyst"

    def status(self) -> CatalystProviderStatus:
        configured = _bool_env("EXTERNAL_CATALYST_DISCOVERY_ENABLED") and bool(os.getenv("FMP_API_KEY"))
        warnings = []
        if not _bool_env("EXTERNAL_CATALYST_DISCOVERY_ENABLED"):
            warnings.append("External catalyst discovery is disabled; set EXTERNAL_CATALYST_DISCOVERY_ENABLED=true to enable FMP catalyst discovery.")
        elif not os.getenv("FMP_API_KEY"):
            warnings.append("FMP_API_KEY is not configured; FMP catalyst discovery was skipped.")
        return CatalystProviderStatus(
            provider_name=self.name,
            configured=configured,
            attempted=False,
            available=False,
            warnings=warnings,
        )

    def discover(self, request: CatalystDiscoveryRequest) -> tuple[list[dict[str, Any]], CatalystProviderStatus]:
        status = self.status()
        status.attempted = True
        if not status.configured:
            return [], status

        try:
            from realtime.catalyst_enrichment import get_catalyst_snapshot
        except Exception as exc:
            status.errors.append(f"FMP catalyst provider is unavailable: {exc}")
            return [], status

        intent = _as_dict(request.intent_constraints)
        requested_types = set(_as_list(intent.get("catalyst_types")))
        require_earnings = bool(intent.get("require_upcoming_earnings"))
        earnings_window = int(intent.get("earnings_window_days") or 14)
        candidates: list[dict[str, Any]] = []
        for ticker in _seed_tickers(request):
            try:
                snapshot = get_catalyst_snapshot(ticker, lookback_days=7)
            except Exception as exc:
                status.warnings.append(f"FMP catalyst lookup failed for {ticker}: {exc}")
                continue
            if not isinstance(snapshot, dict) or not snapshot.get("ok"):
                error = snapshot.get("error") if isinstance(snapshot, dict) else "Provider returned malformed catalyst data."
                if error:
                    status.warnings.append(f"FMP catalyst lookup unavailable for {ticker}: {error}")
                continue

            data = _as_dict(snapshot.get("data"))
            news = _as_dict(data.get("news_snapshot"))
            earnings = _as_dict(data.get("earnings_snapshot"))
            catalyst_score = _as_dict(data.get("catalyst_score"))
            days_until = earnings.get("days_until_earnings")
            if require_earnings and not (isinstance(days_until, int) and 0 <= days_until <= earnings_window):
                continue

            catalyst_type = "earnings" if isinstance(days_until, int) and days_until >= 0 else "news"
            if requested_types and catalyst_type not in requested_types and not (catalyst_type == "news" and "analyst" in requested_types):
                continue

            news_items = _as_list(news.get("items"))
            headline = None
            url = None
            published_at = None
            if news_items and isinstance(news_items[0], dict):
                headline = str(news_items[0].get("title") or "").strip() or None
                url = news_items[0].get("url")
                published_at = news_items[0].get("published_at")
            if catalyst_type == "earnings":
                headline = headline or f"Upcoming earnings in {days_until} days."
            reason = catalyst_score.get("summary") or headline or "FMP catalyst data returned a current event signal."
            score = safe_float(catalyst_score.get("catalyst_score"), 50.0)
            if catalyst_type == "earnings":
                score += max(0.0, 12.0 - min(float(days_until or 0), 12.0))
            candidate = CatalystCandidate(
                ticker=ticker,
                source=self.name,
                catalyst_type=catalyst_type,
                title=headline or reason,
                headline=headline,
                url=url,
                published_at=published_at,
                discovered_at=request.discovered_at,
                as_of=published_at or earnings.get("earnings_date") or snapshot.get("timestamp") or request.discovered_at,
                discovery_score=max(30.0, min(95.0, score)),
                confidence=0.75 if catalyst_type == "earnings" else 0.65,
                reason_discovered=reason,
                raw_metadata={
                    "source_payload": {
                        "earnings_date": earnings.get("earnings_date"),
                        "days_until_earnings": days_until,
                        "catalyst_label": catalyst_score.get("catalyst_label"),
                    }
                },
            )
            candidates.append(candidate.to_dict())

        status.available = bool(candidates)
        return candidates[: request.max_tickers], status


class SecFilingsCatalystProvider:
    name = "sec_filings"

    def status(self) -> CatalystProviderStatus:
        enabled = _bool_env("EXTERNAL_CATALYST_SEC_ENABLED")
        configured = enabled and bool(os.getenv("SEC_USER_AGENT"))
        warnings = []
        if not enabled:
            warnings.append("SEC catalyst discovery is disabled; set EXTERNAL_CATALYST_SEC_ENABLED=true to enable recent-filing discovery.")
        elif not os.getenv("SEC_USER_AGENT"):
            warnings.append("SEC_USER_AGENT is not configured; SEC filing catalyst discovery was skipped.")
        return CatalystProviderStatus(
            provider_name=self.name,
            configured=configured,
            attempted=False,
            available=False,
            warnings=warnings,
        )

    def discover(self, request: CatalystDiscoveryRequest) -> tuple[list[dict[str, Any]], CatalystProviderStatus]:
        status = self.status()
        status.attempted = True
        if not status.configured:
            return [], status

        try:
            from research.sec_edgar_provider import fetch_recent_filings
        except Exception as exc:
            status.errors.append(f"SEC filing provider is unavailable: {exc}")
            return [], status

        requested_types = set(_as_list(_as_dict(request.intent_constraints).get("catalyst_types")))
        if requested_types and not requested_types.intersection({"filings", "insider", "earnings", "news"}):
            return [], status

        candidates: list[dict[str, Any]] = []
        for ticker in _seed_tickers(request):
            try:
                filings = fetch_recent_filings(ticker, forms=["8-K", "10-Q", "10-K", "S-1"], limit=3, config={"SEC_RESEARCH_ENABLED": "true"})
            except Exception as exc:
                status.warnings.append(f"SEC filing lookup failed for {ticker}: {exc}")
                continue
            if not isinstance(filings, dict) or not filings.get("ok"):
                status.warnings.extend(str(item) for item in _as_list(filings.get("errors")) if item)
                status.warnings.extend(str(item) for item in _as_list(filings.get("warnings")) if item)
                continue
            for filing in _as_list(filings.get("filings")):
                if not isinstance(filing, dict):
                    continue
                form = str(filing.get("form") or "filing").upper()
                catalyst_type = "filings"
                if form == "8-K":
                    catalyst_type = "filings"
                title = f"{form} filed {filing.get('filing_date') or ''}".strip()
                description = str(filing.get("description") or "").strip()
                reason = description or title
                candidate = CatalystCandidate(
                    ticker=ticker,
                    source=self.name,
                    catalyst_type=catalyst_type,
                    title=title,
                    headline=description or title,
                    url=filing.get("filing_url"),
                    published_at=filing.get("filing_date"),
                    discovered_at=request.discovered_at,
                    as_of=filing.get("filing_date") or request.discovered_at,
                    discovery_score=72.0 if form == "8-K" else 62.0,
                    confidence=0.8,
                    reason_discovered=f"Recent SEC filing: {reason}",
                    raw_metadata={"form": form, "accession_number": filing.get("accession_number")},
                )
                candidates.append(candidate.to_dict())
                break

        status.available = bool(candidates)
        return candidates[: request.max_tickers], status


def configured_catalyst_providers() -> list[CatalystProvider]:
    names = _env_list("EXTERNAL_CATALYST_PROVIDERS") or ["fmp_catalyst", "sec_filings"]
    providers: list[CatalystProvider] = []
    for name in unique_texts(names):
        if name == "fmp_catalyst":
            providers.append(FmpCatalystProvider())
        elif name == "sec_filings":
            providers.append(SecFilingsCatalystProvider())
    return providers
