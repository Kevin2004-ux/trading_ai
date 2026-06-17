import json

import pytest

from research import sec_edgar_provider


def _submissions_payload():
    return {
        "filings": {
            "recent": {
                "accessionNumber": ["0000320193-26-000001", "0000320193-26-000002"],
                "form": ["8-K", "10-Q"],
                "filingDate": ["2026-06-01", "2026-05-01"],
                "reportDate": ["2026-05-31", "2026-03-31"],
                "primaryDocument": ["aapl-20260601.htm", "aapl-20260501.htm"],
                "primaryDocDescription": ["Earnings release", "Quarterly report"],
                "items": ["2.02,9.01", ""],
            }
        }
    }


def test_lookup_cik_for_ticker_uses_cache(tmp_path):
    cache_path = tmp_path / "tickers.json"
    cache_path.write_text(json.dumps({"0": {"ticker": "AAPL", "cik_str": 320193, "title": "Apple Inc."}}))

    result = sec_edgar_provider.lookup_cik_for_ticker("aapl", cache_path=str(cache_path))

    assert result["ok"] is True
    assert result["ticker"] == "AAPL"
    assert result["cik"] == "0000320193"
    assert result["data"]["title"] == "Apple Inc."


def test_fetch_recent_filings_normalizes_filing_schema(monkeypatch, tmp_path):
    monkeypatch.setenv("SEC_USER_AGENT", "trading-ai-test contact@example.com")
    monkeypatch.setattr(
        sec_edgar_provider,
        "lookup_cik_for_ticker",
        lambda ticker, cache_path=None: {"ok": True, "ticker": ticker, "cik": "0000320193", "filings": [], "warnings": [], "errors": []},
    )
    monkeypatch.setattr(
        sec_edgar_provider,
        "fetch_company_submissions",
        lambda cik, config=None: {"ok": True, "ticker": "", "cik": cik, "filings": [], "data": _submissions_payload(), "warnings": [], "errors": []},
    )

    result = sec_edgar_provider.fetch_recent_filings(
        "AAPL",
        forms=["8-K"],
        limit=5,
        config={"SEC_RESEARCH_ENABLED": "true", "SEC_CACHE_DIR": str(tmp_path)},
    )

    assert result["ok"] is True
    assert len(result["filings"]) == 1
    filing = result["filings"][0]
    assert filing["form"] == "8-K"
    assert filing["filing_date"] == "2026-06-01"
    assert filing["items"] == ["2.02", "9.01"]
    assert filing["filing_url"].endswith("/320193/000032019326000001/aapl-20260601.htm")


def test_fetch_company_submissions_requires_user_agent_when_enabled(monkeypatch, tmp_path):
    monkeypatch.delenv("SEC_USER_AGENT", raising=False)

    result = sec_edgar_provider.fetch_company_submissions(
        "320193",
        config={"SEC_RESEARCH_ENABLED": "true", "SEC_CACHE_DIR": str(tmp_path)},
    )

    assert result["ok"] is False
    assert "SEC_USER_AGENT" in result["errors"][0]


def test_fetch_filing_text_returns_structured_network_errors(monkeypatch):
    class Boom(Exception):
        pass

    monkeypatch.setattr(sec_edgar_provider, "_get_text", lambda *args, **kwargs: (_ for _ in ()).throw(Boom("network down")))

    result = sec_edgar_provider.fetch_filing_text("https://www.sec.gov/test.htm", config={"SEC_RESEARCH_ENABLED": "true", "SEC_USER_AGENT": "ua"})

    assert result["ok"] is False
    assert result["text"] is None
    assert "network down" in result["errors"][0]

