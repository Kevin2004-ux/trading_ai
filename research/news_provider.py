from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _config_value(config: dict | None, name: str, default: Any = None) -> Any:
    if isinstance(config, dict) and name in config:
        return config[name]
    return os.getenv(name, default)


def _bool_value(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def _unavailable(provider: str, ticker: str, reason: str) -> dict:
    return {
        "ok": False,
        "provider": provider,
        "available": False,
        "ticker": str(ticker or "").strip().upper(),
        "articles": [],
        "warnings": [reason],
        "errors": [],
    }


def fetch_recent_news(
    ticker: str,
    source: str = "ibkr_optional",
    limit: int = 20,
    config: dict | None = None,
) -> dict:
    normalized = str(ticker or "").strip().upper()
    provider = str(source or _config_value(config, "NEWS_PROVIDER", "ibkr_optional"))
    enabled = _bool_value(_config_value(config, "NEWS_RESEARCH_ENABLED", "false"))
    if not normalized:
        return {"ok": False, "provider": provider, "available": False, "ticker": normalized, "articles": [], "warnings": [], "errors": ["Ticker is required."]}
    if not enabled:
        return _unavailable(provider, normalized, "News research is disabled.")

    if provider != "ibkr_optional":
        return _unavailable(provider, normalized, f"News provider {provider} is not configured.")

    if not _bool_value(_config_value(config, "IBKR_NEWS_DIAGNOSTIC_ENABLED", "false")):
        return _unavailable(provider, normalized, "IBKR news diagnostics are opt-in and disabled.")

    try:
        from providers.ibkr_provider import fetch_ibkr_news  # type: ignore
    except Exception:
        return _unavailable(provider, normalized, "IBKR news provider is not implemented in this runtime.")

    try:
        result = fetch_ibkr_news(normalized, limit=max(int(limit or 0), 1), read_only=True)
    except Exception as exc:
        return {"ok": False, "provider": provider, "available": False, "ticker": normalized, "articles": [], "warnings": [], "errors": [str(exc)]}

    articles = result.get("articles", []) if isinstance(result, dict) and isinstance(result.get("articles"), list) else []
    return {
        "ok": bool(result.get("ok")) if isinstance(result, dict) else False,
        "provider": provider,
        "available": bool(articles),
        "ticker": normalized,
        "articles": articles[: max(int(limit or 0), 1)],
        "warnings": list(result.get("warnings", []) if isinstance(result, dict) else []),
        "errors": list(result.get("errors", []) if isinstance(result, dict) else ["IBKR news provider returned malformed data."]),
    }


def diagnose_news_provider(config: dict | None = None) -> dict:
    provider = str(_config_value(config, "NEWS_PROVIDER", "ibkr_optional"))
    enabled = _bool_value(_config_value(config, "NEWS_RESEARCH_ENABLED", "false"))
    diagnostic_enabled = _bool_value(_config_value(config, "IBKR_NEWS_DIAGNOSTIC_ENABLED", "false"))
    warnings: list[str] = []
    errors: list[str] = []
    available = False

    if not enabled:
        warnings.append("News research is disabled.")
    elif provider == "ibkr_optional" and not diagnostic_enabled:
        warnings.append("IBKR news diagnostics are opt-in and disabled.")
    elif provider == "ibkr_optional":
        try:
            from providers.ibkr_provider import check_ibkr_connection

            connection = check_ibkr_connection()
            available = bool(connection.get("ok"))
            if not available:
                warnings.append(connection.get("error") or "IBKR connection is unavailable.")
        except Exception as exc:
            errors.append(str(exc))
    else:
        warnings.append(f"News provider {provider} is not configured.")

    return {
        "ok": enabled and (available or bool(warnings)) and not errors,
        "provider": provider,
        "available": available,
        "timestamp": _now_iso(),
        "warnings": warnings,
        "errors": errors,
    }
