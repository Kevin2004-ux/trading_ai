from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import pandas as pd
import requests

import config


SOURCE_UNAVAILABLE = "unavailable"
SOURCE_FMP = "fmp"
FMP_BASE_URL = "https://financialmodelingprep.com/api/v3"

POSITIVE_KEYWORDS = {
    "upgrade": 9,
    "price target raise": 9,
    "raises price target": 8,
    "beats": 8,
    "beat": 7,
    "product launch": 7,
    "contract": 6,
    "partnership": 6,
    "win": 6,
    "award": 5,
    "guidance reaffirmed": 5,
    "strong demand": 5,
    "record revenue": 8,
}
NEGATIVE_KEYWORDS = {
    "downgrade": 9,
    "guidance cut": 10,
    "cuts guidance": 10,
    "lawsuit": 10,
    "investigation": 10,
    "sec": 8,
    "offering": 8,
    "dilution": 9,
    "miss": 7,
    "weak demand": 6,
    "recall": 8,
    "probe": 9,
    "bankruptcy": 10,
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _response(
    ok: bool,
    ticker: str,
    *,
    source: str,
    data: dict | None = None,
    error: str | None = None,
) -> dict:
    payload = {
        "ok": ok,
        "ticker": str(ticker or "").strip().upper(),
        "source": source,
        "timestamp": _now_iso(),
        "error": error,
    }
    if data:
        payload.update(data)
    return payload


def _get_fmp_api_key() -> str | None:
    return getattr(config, "FMP_API_KEY", None)


def _normalize_timestamp(value: Any) -> str | None:
    if value in (None, ""):
        return None
    try:
        ts = pd.Timestamp(value)
    except Exception:
        return None
    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    else:
        ts = ts.tz_convert("UTC")
    return ts.isoformat()


def _parse_days_until(value: Any) -> int | None:
    iso_value = _normalize_timestamp(value)
    if not iso_value:
        return None
    target = pd.Timestamp(iso_value)
    now = pd.Timestamp(datetime.now(timezone.utc))
    return int((target.normalize() - now.normalize()).days)


def _contains_phrase(text: str, phrase: str) -> bool:
    return phrase in text


def _keyword_sentiment(title: str, summary: str) -> tuple[str, float, list[str], list[str]]:
    text = f"{title} {summary}".lower()
    positives: list[str] = []
    negatives: list[str] = []
    pos_score = 0.0
    neg_score = 0.0

    for keyword, weight in POSITIVE_KEYWORDS.items():
        if _contains_phrase(text, keyword):
            positives.append(keyword)
            pos_score += weight

    for keyword, weight in NEGATIVE_KEYWORDS.items():
        if _contains_phrase(text, keyword):
            negatives.append(keyword)
            neg_score += weight

    if pos_score > neg_score:
        sentiment = "positive"
    elif neg_score > pos_score:
        sentiment = "negative"
    elif pos_score == 0 and neg_score == 0:
        sentiment = "unknown"
    else:
        sentiment = "neutral"

    relevance_score = max(pos_score, neg_score)
    return sentiment, min(relevance_score, 10.0), positives, negatives


def get_news_snapshot(
    ticker: str,
    lookback_days: int = 7,
    max_items: int = 10,
) -> dict:
    normalized_ticker = str(ticker or "").strip().upper()
    api_key = _get_fmp_api_key()
    if not api_key:
        return _response(
            False,
            normalized_ticker,
            source=SOURCE_UNAVAILABLE,
            data={"lookback_days": lookback_days, "items": []},
            error="FMP_API_KEY is not configured.",
        )

    try:
        url = (
            f"{FMP_BASE_URL}/stock_news"
            f"?tickers={normalized_ticker}&limit={max_items}&apikey={api_key}"
        )
        response = requests.get(url, timeout=20)
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, list) or not payload:
            return _response(
                False,
                normalized_ticker,
                source=SOURCE_FMP,
                data={"lookback_days": lookback_days, "items": []},
                error="No news items were returned by the provider.",
            )

        cutoff = datetime.now(timezone.utc) - timedelta(days=lookback_days)
        items: list[dict] = []
        for raw_item in payload:
            if not isinstance(raw_item, dict):
                continue
            published_at = _normalize_timestamp(raw_item.get("publishedDate") or raw_item.get("published_at"))
            if published_at:
                published_ts = pd.Timestamp(published_at).to_pydatetime()
                if published_ts < cutoff:
                    continue
            title = str(raw_item.get("title") or "").strip()
            summary = str(raw_item.get("text") or raw_item.get("summary") or "").strip()
            sentiment, relevance_score, _, _ = _keyword_sentiment(title, summary)
            items.append(
                {
                    "title": title,
                    "published_at": published_at,
                    "source": raw_item.get("site") or raw_item.get("source") or SOURCE_FMP,
                    "url": raw_item.get("url"),
                    "summary": summary,
                    "sentiment": sentiment,
                    "relevance_score": relevance_score,
                }
            )
            if len(items) >= max_items:
                break

        if not items:
            return _response(
                False,
                normalized_ticker,
                source=SOURCE_FMP,
                data={"lookback_days": lookback_days, "items": []},
                error="No recent news items matched the requested lookback window.",
            )

        return _response(
            True,
            normalized_ticker,
            source=SOURCE_FMP,
            data={"lookback_days": lookback_days, "items": items},
        )
    except requests.exceptions.RequestException as exc:
        return _response(
            False,
            normalized_ticker,
            source=SOURCE_FMP,
            data={"lookback_days": lookback_days, "items": []},
            error=f"Failed to fetch news snapshot: {exc}",
        )
    except Exception as exc:
        return _response(
            False,
            normalized_ticker,
            source=SOURCE_FMP,
            data={"lookback_days": lookback_days, "items": []},
            error=f"Unexpected error while fetching news snapshot: {exc}",
        )


def get_earnings_snapshot(
    ticker: str,
) -> dict:
    normalized_ticker = str(ticker or "").strip().upper()
    api_key = _get_fmp_api_key()
    if not api_key:
        return _response(
            False,
            normalized_ticker,
            source=SOURCE_UNAVAILABLE,
            data={
                "earnings_date": None,
                "days_until_earnings": None,
                "is_earnings_risk": False,
            },
            error="FMP_API_KEY is not configured.",
        )

    try:
        url = f"{FMP_BASE_URL}/historical/earning_calendar/{normalized_ticker}?limit=4&apikey={api_key}"
        response = requests.get(url, timeout=20)
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, list) or not payload:
            return _response(
                False,
                normalized_ticker,
                source=SOURCE_FMP,
                data={
                    "earnings_date": None,
                    "days_until_earnings": None,
                    "is_earnings_risk": False,
                },
                error="No earnings data was returned by the provider.",
            )

        future_rows = []
        for row in payload:
            if not isinstance(row, dict):
                continue
            earnings_date = row.get("date") or row.get("fillingDate") or row.get("updatedFromDate")
            days_until = _parse_days_until(earnings_date)
            if days_until is not None and days_until >= 0:
                future_rows.append((days_until, earnings_date))

        if not future_rows:
            return _response(
                True,
                normalized_ticker,
                source=SOURCE_FMP,
                data={
                    "earnings_date": None,
                    "days_until_earnings": None,
                    "is_earnings_risk": False,
                },
            )

        days_until_earnings, earnings_date = sorted(future_rows, key=lambda item: item[0])[0]
        return _response(
            True,
            normalized_ticker,
            source=SOURCE_FMP,
            data={
                "earnings_date": _normalize_timestamp(earnings_date),
                "days_until_earnings": days_until_earnings,
                "is_earnings_risk": days_until_earnings <= 7,
            },
        )
    except requests.exceptions.RequestException as exc:
        return _response(
            False,
            normalized_ticker,
            source=SOURCE_FMP,
            data={
                "earnings_date": None,
                "days_until_earnings": None,
                "is_earnings_risk": False,
            },
            error=f"Failed to fetch earnings snapshot: {exc}",
        )
    except Exception as exc:
        return _response(
            False,
            normalized_ticker,
            source=SOURCE_FMP,
            data={
                "earnings_date": None,
                "days_until_earnings": None,
                "is_earnings_risk": False,
            },
            error=f"Unexpected error while fetching earnings snapshot: {exc}",
        )


def score_catalyst_strength(
    news_snapshot: dict | None = None,
    earnings_snapshot: dict | None = None,
    market_snapshot: dict | None = None,
    filing_context: dict | None = None,
    earnings_transcript_context: dict | None = None,
) -> dict:
    news_snapshot = news_snapshot or {}
    earnings_snapshot = earnings_snapshot or {}
    market_snapshot = market_snapshot or {}

    positive_catalysts: list[str] = []
    negative_catalysts: list[str] = []
    risk_flags: list[str] = []
    score = 50.0

    news_items = news_snapshot.get("items", []) if isinstance(news_snapshot, dict) else []
    positive_news = 0
    negative_news = 0

    for item in news_items:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "")
        summary = str(item.get("summary") or "")
        sentiment = str(item.get("sentiment") or "unknown").lower()
        _, relevance_score, positives, negatives = _keyword_sentiment(title, summary)
        if sentiment == "positive":
            positive_news += 1
            score += min(10.0, relevance_score)
            positive_catalysts.extend(positives or [title[:80]])
        elif sentiment == "negative":
            negative_news += 1
            score -= min(12.0, relevance_score)
            negative_catalysts.extend(negatives or [title[:80]])

    if positive_news >= 2:
        positive_catalysts.append("Multiple recent positive news items.")
        score += 6.0
    if negative_news >= 2:
        negative_catalysts.append("Multiple recent negative news items.")
        score -= 8.0

    if isinstance(earnings_snapshot, dict):
        days_until = earnings_snapshot.get("days_until_earnings")
        is_earnings_risk = bool(earnings_snapshot.get("is_earnings_risk"))
        if is_earnings_risk:
            risk_flags.append("Earnings are within 7 days.")
            score -= 15.0
        elif isinstance(days_until, int) and days_until < 0:
            positive_catalysts.append("Earnings event has already passed.")
            score += 3.0

    technical = {}
    if isinstance(market_snapshot, dict):
        market_data = market_snapshot.get("data", {}) if "data" in market_snapshot else market_snapshot
        technical = market_data.get("technical_snapshot", {}) if isinstance(market_data, dict) else {}
    if isinstance(technical, dict):
        relative_volume = technical.get("relative_volume")
        daily_return = technical.get("daily_return")
        atr_percent = technical.get("atr_percent")

        try:
            if relative_volume is not None and float(relative_volume) >= 1.8 and positive_news:
                positive_catalysts.append("High relative volume confirms the catalyst move.")
                score += 7.0
            if atr_percent is not None and float(atr_percent) >= 7.0 and not positive_news and not negative_news:
                risk_flags.append("High volatility with unclear catalyst.")
                score -= 8.0
            if daily_return is not None and float(daily_return) < -2.0 and positive_news:
                negative_catalysts.append("Weak price reaction after supposedly positive news.")
                score -= 7.0
        except (TypeError, ValueError):
            pass

    filing_context = filing_context or {}
    filing_data = filing_context.get("data", {}) if isinstance(filing_context, dict) else {}
    filing_analysis = filing_data.get("filing_analysis", {}) if isinstance(filing_data, dict) else {}
    if isinstance(filing_analysis, dict):
        filing_risk_label = str(filing_analysis.get("filing_risk_label", "")).lower()
        if filing_risk_label == "high":
            risk_flags.append("SEC filing risk is high.")
            score -= 14.0
        elif filing_risk_label == "medium":
            risk_flags.append("SEC filing risk is elevated.")
            score -= 6.0
        positive_filing_signals = filing_analysis.get("positive_filing_signals", [])
        if isinstance(positive_filing_signals, list) and positive_filing_signals:
            positive_catalysts.append(positive_filing_signals[0])
            score += 4.0

    earnings_transcript_context = earnings_transcript_context or {}
    transcript_data = earnings_transcript_context.get("data", {}) if isinstance(earnings_transcript_context, dict) else {}
    earnings_quality = transcript_data.get("earnings_quality", {}) if isinstance(transcript_data, dict) else {}
    if isinstance(earnings_quality, dict):
        earnings_quality_label = str(earnings_quality.get("earnings_quality_label", "")).lower()
        guidance_label = str(earnings_quality.get("guidance_label", "")).lower()
        management_tone = str(earnings_quality.get("management_tone", "")).lower()
        if earnings_quality_label == "strong":
            positive_catalysts.append("Recent earnings transcript quality is strong.")
            score += 8.0
        elif earnings_quality_label == "weak":
            negative_catalysts.append("Recent earnings transcript quality is weak.")
            score -= 10.0
        if guidance_label == "lowered":
            negative_catalysts.append("Management lowered guidance.")
            risk_flags.append("Recent transcript guidance was lowered.")
            score -= 10.0
        elif guidance_label == "raised":
            positive_catalysts.append("Management raised guidance.")
            score += 6.0
        if management_tone in {"cautious", "negative"}:
            risk_flags.append("Management tone was cautious or negative.")
            score -= 5.0

    news_ok = bool(news_snapshot.get("ok")) if isinstance(news_snapshot, dict) else False
    earnings_ok = bool(earnings_snapshot.get("ok")) if isinstance(earnings_snapshot, dict) else False
    filing_ok = bool(filing_context.get("ok")) if isinstance(filing_context, dict) else False
    transcript_ok = bool(earnings_transcript_context.get("ok")) if isinstance(earnings_transcript_context, dict) else False
    if not news_ok and not earnings_ok and not filing_ok and not transcript_ok:
        return {
            "catalyst_score": 0.0,
            "catalyst_label": "unavailable",
            "positive_catalysts": [],
            "negative_catalysts": [],
            "risk_flags": [],
            "summary": "Catalyst data is unavailable.",
        }

    score = max(0.0, min(100.0, score))
    if risk_flags and score <= 40:
        label = "high_risk"
    elif score >= 75:
        label = "strong_positive"
    elif score >= 60:
        label = "positive"
    elif score <= 35:
        label = "negative"
    else:
        label = "neutral"

    summary_parts = []
    if positive_catalysts:
        summary_parts.append(f"Positive: {positive_catalysts[0]}")
    if negative_catalysts:
        summary_parts.append(f"Negative: {negative_catalysts[0]}")
    if risk_flags:
        summary_parts.append(f"Risk: {risk_flags[0]}")
    summary = " ".join(summary_parts) if summary_parts else "Catalyst picture is neutral."

    return {
        "catalyst_score": round(score, 2),
        "catalyst_label": label,
        "positive_catalysts": list(dict.fromkeys(positive_catalysts)),
        "negative_catalysts": list(dict.fromkeys(negative_catalysts)),
        "risk_flags": list(dict.fromkeys(risk_flags)),
        "summary": summary,
    }


def get_catalyst_snapshot(
    ticker: str,
    lookback_days: int = 7,
) -> dict:
    news_snapshot = get_news_snapshot(ticker, lookback_days=lookback_days)
    earnings_snapshot = get_earnings_snapshot(ticker)
    catalyst_score = score_catalyst_strength(
        news_snapshot=news_snapshot,
        earnings_snapshot=earnings_snapshot,
        market_snapshot=None,
    )
    return {
        "ok": bool(news_snapshot.get("ok")) or bool(earnings_snapshot.get("ok")),
        "ticker": str(ticker or "").strip().upper(),
        "source": SOURCE_FMP if news_snapshot.get("source") == SOURCE_FMP or earnings_snapshot.get("source") == SOURCE_FMP else SOURCE_UNAVAILABLE,
        "timestamp": _now_iso(),
        "data": {
            "news_snapshot": news_snapshot,
            "earnings_snapshot": earnings_snapshot,
            "catalyst_score": catalyst_score,
        },
        "error": None if (bool(news_snapshot.get("ok")) or bool(earnings_snapshot.get("ok"))) else (
            news_snapshot.get("error") or earnings_snapshot.get("error") or "Catalyst data is unavailable."
        ),
    }


def enrich_candidate_with_catalysts(
    candidate: dict,
    lookback_days: int = 7,
) -> dict:
    enriched = dict(candidate)
    ticker = str(enriched.get("ticker") or "").strip().upper()
    market_snapshot = {
        "data": {
            "technical_snapshot": enriched.get("technical_snapshot", {}) if isinstance(enriched.get("technical_snapshot"), dict) else {}
        }
    }
    news_snapshot = get_news_snapshot(ticker, lookback_days=lookback_days)
    earnings_snapshot = get_earnings_snapshot(ticker)
    catalyst_score = score_catalyst_strength(
        news_snapshot=news_snapshot,
        earnings_snapshot=earnings_snapshot,
        market_snapshot=market_snapshot,
    )
    enriched["catalyst_context"] = {
        "news_snapshot": news_snapshot,
        "earnings_snapshot": earnings_snapshot,
        **catalyst_score,
        "has_news_catalyst_data": bool(news_snapshot.get("ok")) or bool(earnings_snapshot.get("ok")),
        "catalyst_bias": round((float(catalyst_score["catalyst_score"]) - 50.0) / 10.0, 2) if catalyst_score["catalyst_label"] != "unavailable" else 0.0,
    }
    return enriched
