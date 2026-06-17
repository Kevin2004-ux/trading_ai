from __future__ import annotations

import json
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests


SEC_DATA_URL = "https://data.sec.gov"
SEC_ARCHIVES_URL = "https://www.sec.gov/Archives/edgar/data"
SEC_TICKER_URL = "https://www.sec.gov/files/company_tickers.json"
DEFAULT_CACHE_DIR = Path(".cache/sec_edgar")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _bool_env(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def _config_value(config: dict | None, name: str, default: Any = None) -> Any:
    if isinstance(config, dict) and name in config:
        return config[name]
    return os.getenv(name, default)


def _sec_enabled(config: dict | None = None) -> bool:
    return str(_config_value(config, "SEC_RESEARCH_ENABLED", _config_value(config, "ENABLE_SEC_RESEARCH", "true"))).lower() in {"1", "true", "yes", "y", "on"}


def _user_agent(config: dict | None = None) -> str | None:
    value = _config_value(config, "SEC_USER_AGENT")
    return str(value).strip() if value else None


def _cache_enabled(config: dict | None = None) -> bool:
    return str(_config_value(config, "SEC_CACHE_ENABLED", "true")).lower() in {"1", "true", "yes", "y", "on"}


def _cache_ttl(config: dict | None = None) -> timedelta:
    try:
        hours = float(_config_value(config, "SEC_CACHE_TTL_HOURS", 24))
    except (TypeError, ValueError):
        hours = 24
    return timedelta(hours=max(hours, 0))


def _cache_dir(config: dict | None = None) -> Path:
    value = _config_value(config, "SEC_CACHE_DIR")
    return Path(value).expanduser() if value else DEFAULT_CACHE_DIR


def _headers(config: dict | None = None) -> dict | None:
    agent = _user_agent(config)
    if not _sec_enabled(config):
        return {"User-Agent": agent or "trading-ai research disabled contact@example.com"}
    if not agent:
        return None
    return {"User-Agent": agent, "Accept-Encoding": "gzip, deflate"}


def _response(ok: bool, ticker: str = "", cik: str | None = None, *, filings: list[dict] | None = None, data: dict | None = None, warnings: list[str] | None = None, errors: list[str] | None = None) -> dict:
    payload = {
        "ok": ok,
        "ticker": str(ticker or "").upper(),
        "cik": cik,
        "filings": filings or [],
        "warnings": warnings or [],
        "errors": errors or [],
    }
    if data is not None:
        payload["data"] = data
    return payload


def _read_cache(path: Path, ttl: timedelta) -> Any | None:
    if not path.exists():
        return None
    try:
        if ttl.total_seconds() > 0 and datetime.now(timezone.utc) - datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc) > ttl:
            return None
        return json.loads(path.read_text())
    except Exception:
        return None


def _write_cache(path: Path, payload: Any) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload))
    except Exception:
        return


def _get_json(url: str, config: dict | None = None) -> dict:
    headers = _headers(config)
    if headers is None:
        raise RuntimeError("SEC_USER_AGENT is required when SEC research is enabled.")
    rps = float(_config_value(config, "SEC_REQUESTS_PER_SECOND", 5) or 5)
    if rps > 0:
        time.sleep(min(1.0 / rps, 0.25))
    response = requests.get(url, headers=headers, timeout=20)
    response.raise_for_status()
    return response.json()


def _get_text(url: str, config: dict | None = None) -> str:
    headers = _headers(config)
    if headers is None:
        raise RuntimeError("SEC_USER_AGENT is required when SEC research is enabled.")
    response = requests.get(url, headers=headers, timeout=20)
    response.raise_for_status()
    return response.text


def _normalize_cik(value: Any) -> str | None:
    try:
        return str(int(value)).zfill(10)
    except (TypeError, ValueError):
        value = str(value or "").strip()
        return value.zfill(10) if value.isdigit() else None


def lookup_cik_for_ticker(ticker: str, cache_path: str | None = None) -> dict:
    normalized = str(ticker or "").strip().upper()
    if not normalized:
        return _response(False, normalized, errors=["Ticker is required."])
    cache_file = Path(cache_path).expanduser() if cache_path else DEFAULT_CACHE_DIR / "company_tickers.json"
    payload = _read_cache(cache_file, timedelta(hours=24))
    try:
        if payload is None:
            payload = _get_json(SEC_TICKER_URL, {"SEC_USER_AGENT": os.getenv("SEC_USER_AGENT") or "trading-ai tests contact@example.com", "SEC_RESEARCH_ENABLED": "false"})
            _write_cache(cache_file, payload)
        rows = payload.values() if isinstance(payload, dict) else payload
        for row in rows:
            if isinstance(row, dict) and str(row.get("ticker", "")).upper() == normalized:
                cik = _normalize_cik(row.get("cik_str") or row.get("cik"))
                return _response(True, normalized, cik, data={"title": row.get("title")})
        return _response(False, normalized, errors=[f"CIK not found for ticker {normalized}."])
    except Exception as exc:
        return _response(False, normalized, errors=[f"Failed to lookup CIK: {exc}"])


def fetch_company_submissions(cik: str, config: dict | None = None) -> dict:
    normalized_cik = _normalize_cik(cik)
    if not normalized_cik:
        return _response(False, cik=str(cik or ""), errors=["Valid CIK is required."])
    if _sec_enabled(config) and not _user_agent(config):
        return _response(False, cik=normalized_cik, errors=["SEC_USER_AGENT is required when SEC research is enabled."])
    cache_file = _cache_dir(config) / f"submissions_{normalized_cik}.json"
    payload = _read_cache(cache_file, _cache_ttl(config)) if _cache_enabled(config) else None
    try:
        if payload is None:
            payload = _get_json(f"{SEC_DATA_URL}/submissions/CIK{normalized_cik}.json", config=config)
            if _cache_enabled(config):
                _write_cache(cache_file, payload)
        return _response(True, cik=normalized_cik, data=payload)
    except Exception as exc:
        return _response(False, cik=normalized_cik, errors=[f"Failed to fetch SEC submissions: {exc}"])


def _filing_url(cik: str, accession: str, primary_document: str | None) -> str | None:
    if not accession or not primary_document:
        return None
    compact = accession.replace("-", "")
    return f"{SEC_ARCHIVES_URL}/{int(cik)}/{compact}/{primary_document}"


def _parse_recent_filings(ticker: str, cik: str, submissions: dict, forms: list[str] | None, limit: int) -> list[dict]:
    recent = ((submissions.get("filings") or {}).get("recent") or {}) if isinstance(submissions, dict) else {}
    forms_filter = {str(item).upper() for item in forms} if forms else None
    rows = []
    accessions = recent.get("accessionNumber", []) or []
    for index, accession in enumerate(accessions):
        form = str((recent.get("form") or [None])[index] or "OTHER").upper()
        if forms_filter and form not in forms_filter:
            continue
        primary = (recent.get("primaryDocument") or [None])[index]
        filing = {
            "accession_number": accession,
            "form": form if form in {"8-K", "10-Q", "10-K", "S-1"} else "OTHER",
            "filing_date": (recent.get("filingDate") or [None])[index],
            "report_date": (recent.get("reportDate") or [None])[index],
            "primary_document": primary,
            "filing_url": _filing_url(cik, accession, primary),
            "description": (recent.get("primaryDocDescription") or [None])[index] or "",
            "items": str((recent.get("items") or [""])[index] or "").split(",") if recent.get("items") else [],
            "ticker": ticker,
            "cik": cik,
        }
        rows.append(filing)
        if len(rows) >= limit:
            break
    return rows


def fetch_recent_filings(
    ticker: str,
    forms: list[str] | None = None,
    limit: int = 20,
    config: dict | None = None,
) -> dict:
    normalized = str(ticker or "").strip().upper()
    if not _sec_enabled(config):
        return _response(False, normalized, warnings=["SEC research is disabled."], errors=["SEC research is disabled."])
    lookup = lookup_cik_for_ticker(normalized, cache_path=str(_cache_dir(config) / "company_tickers.json"))
    if not lookup.get("ok"):
        return lookup
    cik = lookup.get("cik")
    submissions = fetch_company_submissions(cik, config=config)
    if not submissions.get("ok"):
        return _response(False, normalized, cik, errors=submissions.get("errors", []))
    filings = _parse_recent_filings(normalized, cik, submissions.get("data", {}), forms, max(int(limit or 0), 1))
    return _response(True, normalized, cik, filings=filings, warnings=[] if filings else ["No recent SEC filings matched the requested filters."])


def fetch_filing_text(
    filing_url: str,
    config: dict | None = None,
) -> dict:
    if not filing_url:
        return {"ok": False, "filing_url": filing_url, "text": None, "warnings": [], "errors": ["filing_url is required."]}
    if not _sec_enabled(config):
        return {"ok": False, "filing_url": filing_url, "text": None, "warnings": ["SEC research is disabled."], "errors": ["SEC research is disabled."]}
    try:
        text = _get_text(filing_url, config=config)
        return {"ok": True, "filing_url": filing_url, "text": text, "warnings": [], "errors": []}
    except Exception as exc:
        return {"ok": False, "filing_url": filing_url, "text": None, "warnings": [], "errors": [f"Failed to fetch filing text: {exc}"]}
