from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Callable

import config
from analytics.timeframe_confirmation import evaluate_timeframe_confirmation
from analytics.volume_profile import evaluate_volume_profile_confirmation
from config.runtime_readiness import check_runtime_readiness
from memory.vector_memory import find_similar_setups, get_memory_config
from memory.annotation_store import add_human_annotation, record_memory_retrieval_event
from memory.retrieval_quality import evaluate_retrieval_quality
from macro.macro_risk import evaluate_macro_risk
from options.options_risk import evaluate_option_trade_risk
from options.strategy_builder import build_option_strategy_candidates
from providers.market_data_provider import get_selected_market_data_provider
from providers.options_data_provider import get_selected_options_data_provider
from realtime.catalyst_enrichment import get_news_snapshot
from realtime.market_data import get_market_snapshot
from realtime.options_chain import get_options_chain
from research.earnings_8k_analyzer import analyze_earnings_8k
from research.earnings_transcripts import get_earnings_transcript_snapshot
from research.filing_analyzer import analyze_recent_filings
from research.filing_sentiment import evaluate_filing_sentiment
from research.news_provider import diagnose_news_provider, fetch_recent_news
from research.news_sentiment import evaluate_news_sentiment
from research.sec_edgar_provider import fetch_filing_text, fetch_recent_filings
from research.short_interest import evaluate_short_interest
from simulation.scenario_definitions import list_stress_scenarios
from jobs.job_registry import list_registered_jobs
from jobs.scheduler import build_default_schedule
from alerts.alert_manager import list_alerts
from jobs.job_history import list_job_runs
from tracking.trade_logger import get_trade_history


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _env_or_config(name: str) -> str | None:
    return os.getenv(name) or getattr(config, name, None)


def _skipped(provider: str, reason: str) -> dict:
    return {
        "ok": False,
        "provider": provider,
        "status": "unavailable",
        "usable": False,
        "data": None,
        "error": reason,
    }


def _provider_call(provider: str, fn: Callable[[], dict]) -> dict:
    try:
        result = fn()
        ok = bool(result.get("ok")) if isinstance(result, dict) else False
        status = "usable" if ok else "unavailable"
        return {
            "ok": ok,
            "provider": provider,
            "status": status,
            "usable": ok,
            "data": result,
            "error": None if ok else (result.get("error", "Provider returned an unavailable response.") if isinstance(result, dict) else "Provider returned malformed data."),
        }
    except Exception as exc:
        return {
            "ok": False,
            "provider": provider,
            "status": "failed",
            "usable": False,
            "data": None,
            "error": str(exc),
        }


def _bool_env_or_config(name: str, default: bool = False) -> bool:
    value = _env_or_config(name)
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def _edgar_filing_check(ticker: str) -> dict:
    filings = fetch_recent_filings(
        ticker,
        forms=["8-K", "10-Q", "10-K"],
        limit=10,
        config={"SEC_RESEARCH_ENABLED": "true"},
    )
    filing_rows = filings.get("filings", []) if isinstance(filings, dict) else []
    analysis = analyze_recent_filings(ticker, filing_rows)
    earnings_analysis = None
    earnings_filing = next(
        (
            filing
            for filing in filing_rows
            if isinstance(filing, dict)
            and str(filing.get("form", "")).upper() == "8-K"
            and ("2.02" in " ".join(str(item) for item in filing.get("items", [])) or "earnings" in str(filing.get("description", "")).lower())
        ),
        None,
    )
    if isinstance(earnings_filing, dict):
        text_result = fetch_filing_text(earnings_filing.get("filing_url"), config={"SEC_RESEARCH_ENABLED": "true"}) if earnings_filing.get("filing_url") else {"ok": False}
        filing_text = text_result.get("text") if isinstance(text_result, dict) and text_result.get("ok") else earnings_filing.get("description", "")
        earnings_analysis = analyze_earnings_8k(ticker, earnings_filing, filing_text)
    sentiment = evaluate_filing_sentiment(ticker, analysis, earnings_analysis)
    return {
        "ok": bool(filings.get("ok")) if isinstance(filings, dict) else False,
        "ticker": ticker,
        "source": "sec_edgar",
        "timestamp": _now_iso(),
        "data": {
            "sec_research_enabled": True,
            "filings_loaded": len(filing_rows),
            "filing_analysis_completed": bool(analysis.get("ok")),
            "earnings_8k_analyzed": isinstance(earnings_analysis, dict),
            "filing_sentiment_evaluated": bool(sentiment.get("ok")),
            "filing_analysis": analysis,
            "earnings_8k_analysis": earnings_analysis,
            "filing_sentiment": sentiment,
        },
        "error": None if filings.get("ok") else "; ".join(filings.get("errors", []) or ["SEC EDGAR filings unavailable."]),
    }


def _short_interest_check(ticker: str) -> dict:
    enabled = _bool_env_or_config("SHORT_INTEREST_ENABLED", default=True)
    context = evaluate_short_interest(ticker, short_data=None)
    return {
        "ok": True,
        "ticker": ticker,
        "source": "local",
        "timestamp": _now_iso(),
        "data": {
            "short_interest_research_enabled": enabled,
            "short_interest": context,
            "research_risk_blocks_or_reduces": str(context.get("trade_impact", "")).lower() in {"caution", "blocking"},
        },
        "error": None,
    }


def _news_research_check(ticker: str) -> dict:
    enabled = _bool_env_or_config("NEWS_RESEARCH_ENABLED")
    diagnostic = diagnose_news_provider({"NEWS_RESEARCH_ENABLED": str(enabled).lower()})
    if not enabled:
        return {
            "ok": False,
            "ticker": ticker,
            "source": "news_research",
            "timestamp": _now_iso(),
            "data": {"news_research_enabled": False, "diagnostic": diagnostic},
            "error": "News research is disabled.",
        }
    news = fetch_recent_news(ticker, config={"NEWS_RESEARCH_ENABLED": "true"})
    sentiment = evaluate_news_sentiment(ticker, news.get("articles", []) if isinstance(news, dict) else [])
    return {
        "ok": bool(news.get("ok")) if isinstance(news, dict) else False,
        "ticker": ticker,
        "source": "news_research",
        "timestamp": _now_iso(),
        "data": {
            "news_research_enabled": True,
            "news_provider_available": bool(news.get("available")) if isinstance(news, dict) else False,
            "news": news,
            "headline_risk_status": sentiment.get("headline_risk_level"),
            "news_sentiment": sentiment,
            "research_risk_blocks_or_reduces": str(sentiment.get("trade_impact", "")).lower() in {"caution", "blocking"},
            "diagnostic": diagnostic,
        },
        "error": None if isinstance(news, dict) and news.get("ok") else "; ".join(news.get("warnings", []) or news.get("errors", []) or ["News provider unavailable."]),
    }


def _gemini_validation_capability_check() -> dict:
    from translator.output_validator import validate_gemini_output
    from translator.prompt_templates import build_gemini_system_prompt
    from translator.response_formatter import format_deterministic_fallback_response

    return {
        "ok": True,
        "source": "local",
        "timestamp": _now_iso(),
        "data": {
            "prompt_templates_available": callable(build_gemini_system_prompt),
            "structured_output_validation_available": callable(validate_gemini_output),
            "deterministic_fallback_formatter_available": callable(format_deterministic_fallback_response),
            "last_validation_status": None,
            "gemini_called": False,
        },
        "error": None,
    }


def run_provider_dry_run(
    ticker: str = "AAPL",
    include_market_data: bool = True,
    include_news: bool = True,
    include_sec_filings: bool = True,
    include_earnings_transcripts: bool = True,
    include_options: bool = True,
    include_memory: bool = False,
    db_path: str = "strategy_library.db",
) -> dict:
    normalized_ticker = str(ticker or "AAPL").strip().upper() or "AAPL"
    checks: dict[str, dict] = {}
    warnings: list[str] = [
        "Live provider dry run only. No trades are placed and no final recommendations are logged.",
        "Provider calls may use live API quotas when keys are configured.",
    ]
    errors: list[str] = []
    startup_readiness = check_runtime_readiness({"DATABASE_PATH": db_path}, include_live_checks=False)
    macro_risk = evaluate_macro_risk()
    if isinstance(macro_risk, dict) and macro_risk.get("macro_risk_level") != "low":
        warnings.extend(str(item) for item in macro_risk.get("warnings", []) if item)

    polygon_missing = not _env_or_config("POLYGON_API_KEY")
    fmp_missing = not _env_or_config("FMP_API_KEY")
    market_provider = get_selected_market_data_provider()
    options_provider = get_selected_options_data_provider()

    if market_provider == "ibkr" or options_provider == "ibkr":
        from providers.ibkr_provider import check_ibkr_connection

        checks["ibkr_connection"] = _provider_call("ibkr", check_ibkr_connection)

    if include_market_data:
        if market_provider == "ibkr":
            checks["market_data"] = _provider_call("ibkr", lambda: get_market_snapshot(normalized_ticker))
        elif polygon_missing:
            checks["market_data"] = _skipped("polygon", "POLYGON_API_KEY is not configured.")
        else:
            checks["market_data"] = _provider_call("polygon", lambda: get_market_snapshot(normalized_ticker))
    else:
        checks["market_data"] = _skipped(market_provider, "Market data check was disabled.")

    if include_news:
        if fmp_missing:
            checks["news"] = _skipped("fmp", "FMP_API_KEY is not configured.")
        else:
            checks["news"] = _provider_call("fmp", lambda: get_news_snapshot(normalized_ticker))
    else:
        checks["news"] = _skipped("fmp", "News check was disabled.")

    checks["short_interest_research"] = _provider_call("local_short_interest", lambda: _short_interest_check(normalized_ticker))
    checks["news_research"] = _provider_call("news_research", lambda: _news_research_check(normalized_ticker))
    checks["gemini_validation"] = _provider_call("local_gemini_validation", _gemini_validation_capability_check)
    checks["memory_readiness"] = _provider_call(
        "local_memory_readiness",
        lambda: {
            "ok": True,
            "ticker": normalized_ticker,
            "source": "local",
            "timestamp": _now_iso(),
            "data": {
                "memory_enabled": _bool_env_or_config("MEMORY_ENABLED") or _bool_env_or_config("PINECONE_MEMORY_ENABLED") or _bool_env_or_config("ENABLE_PINECONE_MEMORY"),
                "pinecone_configured": bool(get_memory_config().get("pinecone_configured")),
                "pinecone_index_name": get_memory_config().get("pinecone_index_name"),
                "pinecone_namespace": get_memory_config().get("namespace"),
                "local_fallback_ready": _bool_env_or_config("LOCAL_MEMORY_FALLBACK", default=True),
                "retrieval_quality_gate_available": callable(evaluate_retrieval_quality),
                "annotation_store_available": callable(add_human_annotation) and callable(record_memory_retrieval_event),
            },
            "error": None,
        },
    )
    checks["scheduler_alerts"] = _provider_call(
        "local_scheduler_alerts",
        lambda: {
            "ok": True,
            "ticker": normalized_ticker,
            "source": "local",
            "timestamp": _now_iso(),
            "data": {
                "scheduler_enabled": build_default_schedule().get("scheduler_enabled"),
                "registered_jobs_count": len(list_registered_jobs().get("jobs", [])),
                "alert_system_ready": True,
                "recent_alert_counts": (list_alerts(db_path, limit=20).get("severity_counts") if db_path else {}),
            },
            "error": None,
        },
    )
    checks["performance_analytics"] = _provider_call(
        "local_performance_analytics",
        lambda: {
            "ok": True,
            "ticker": normalized_ticker,
            "source": "local",
            "timestamp": _now_iso(),
            "data": {
                "performance_analytics_available": True,
                "setup_diagnostics_available": True,
                "closed_trade_count": len(
                    [
                        trade for trade in (get_trade_history(db_path) if db_path else [])
                        if isinstance(trade, dict)
                        and str(trade.get("outcome") or trade.get("latest_outcome") or "").lower() in {"win", "loss", "expired", "manual_review", "closed"}
                    ]
                ),
                "latest_performance_report_status": next(
                    (
                        run.get("status")
                        for run in (list_job_runs(db_path, limit=20).get("job_runs", []) if db_path else [])
                        if isinstance(run, dict) and run.get("job_type") == "performance_report"
                    ),
                    None,
                ),
            },
            "error": None,
        },
    )
    checks["stress_testing"] = _provider_call(
        "local_stress_testing",
        lambda: {
            "ok": True,
            "ticker": normalized_ticker,
            "source": "local",
            "timestamp": _now_iso(),
            "data": {
                "stress_testing_available": True,
                "default_scenario_count": list_stress_scenarios().get("scenario_count", 0),
                "runtime_readiness": startup_readiness.get("categories", {}).get("stress_testing_ready"),
                "latest_stress_test_job_status": next(
                    (
                        run.get("status")
                        for run in (list_job_runs(db_path, limit=20).get("job_runs", []) if db_path else [])
                        if isinstance(run, dict) and run.get("job_type") == "stress_test"
                    ),
                    None,
                ),
            },
            "error": None,
        },
    )

    if include_sec_filings:
        sec_enabled = _bool_env_or_config("SEC_RESEARCH_ENABLED") or _bool_env_or_config("ENABLE_SEC_RESEARCH")
        if not sec_enabled:
            checks["sec_filings"] = _skipped("sec_edgar", "SEC research is disabled.")
        elif not _env_or_config("SEC_USER_AGENT"):
            checks["sec_filings"] = _skipped("sec_edgar", "SEC_USER_AGENT is not configured.")
        else:
            checks["sec_filings"] = _provider_call("sec_edgar", lambda: _edgar_filing_check(normalized_ticker))
    else:
        checks["sec_filings"] = _skipped("sec_edgar", "SEC filings check was disabled.")

    if include_earnings_transcripts:
        if fmp_missing:
            checks["earnings_transcripts"] = _skipped("fmp", "FMP_API_KEY is not configured.")
        else:
            checks["earnings_transcripts"] = _provider_call("fmp", lambda: get_earnings_transcript_snapshot(normalized_ticker))
    else:
        checks["earnings_transcripts"] = _skipped("fmp", "Earnings transcripts check was disabled.")

    if include_options:
        if options_provider == "ibkr":
            from providers.ibkr_provider import diagnose_ibkr_option_quotes

            def ibkr_options_check() -> dict:
                diagnostic = diagnose_ibkr_option_quotes(normalized_ticker, max_contracts=5)
                summary = diagnostic.get("permissions_summary") or {}
                option_quotes_available = bool(summary.get("option_quotes_available"))
                contracts_tested = len(diagnostic.get("contracts_tested") or [])
                return {
                    "ok": option_quotes_available,
                    "ticker": normalized_ticker,
                    "source": "ibkr",
                    "timestamp": _now_iso(),
                    "data": {
                        "metadata_available": bool(summary.get("option_metadata_available")),
                        "option_quote_test_attempted": contracts_tested > 0,
                        "contracts_tested": contracts_tested,
                        "option_quotes_available": option_quotes_available,
                        "likely_missing_opra": bool(summary.get("likely_missing_opra")),
                        "option_quote_permission_errors": summary.get("errors", []),
                        "diagnostic": diagnostic,
                    },
                    "error": None if option_quotes_available else "IBKR option quote snapshots are unavailable; options final recommendations remain blocked.",
                }

            checks["options"] = _provider_call("ibkr_options", ibkr_options_check)
        elif polygon_missing:
            checks["options"] = _skipped("polygon_options", "POLYGON_API_KEY is not configured.")
        else:
            checks["options"] = _provider_call("polygon_options", lambda: get_options_chain(normalized_ticker))
    else:
        checks["options"] = _skipped(options_provider, "Options check was disabled.")

    options_payload = ((checks.get("options") or {}).get("data") or {}).get("data")
    if isinstance(options_payload, dict):
        contracts = options_payload.get("contracts")
        diagnostic = options_payload.get("diagnostic")
        if isinstance(contracts, list) and contracts:
            first_contract = next((item for item in contracts if isinstance(item, dict)), None)
            checks["option_risk"] = _provider_call(
                "local_option_risk",
                lambda: {
                    "ok": True,
                    "ticker": normalized_ticker,
                    "source": "local",
                    "timestamp": _now_iso(),
                    "data": {
                        "option_quotes_available": True,
                        "iv_available": first_contract.get("implied_volatility") is not None if isinstance(first_contract, dict) else False,
                        "greeks_available": all(first_contract.get(key) is not None for key in ("delta", "gamma", "theta", "vega")) if isinstance(first_contract, dict) else False,
                        "option_trade_risk": evaluate_option_trade_risk(first_contract or {}),
                        "final_options_blocked_reason": None,
                    },
                    "error": None,
                },
            )
            checks["option_strategy_engine"] = _provider_call(
                "local_option_strategy_engine",
                lambda: {
                    "ok": True,
                    "ticker": normalized_ticker,
                    "source": "local",
                    "timestamp": _now_iso(),
                    "data": {
                        "strategy_engine_available": True,
                        "strategy_result": build_option_strategy_candidates(
                            normalized_ticker,
                            {"ticker": normalized_ticker, "current_price": first_contract.get("underlying_price") or 0.0, "option_bias": "bullish"} if isinstance(first_contract, dict) else {"ticker": normalized_ticker},
                            contracts,
                        ),
                    },
                    "error": None,
                },
            )
        elif isinstance(diagnostic, dict):
            permissions = diagnostic.get("permissions_summary") if isinstance(diagnostic.get("permissions_summary"), dict) else {}
            checks["option_risk"] = _provider_call(
                "local_option_risk",
                lambda: {
                    "ok": True,
                    "ticker": normalized_ticker,
                    "source": "local",
                    "timestamp": _now_iso(),
                    "data": {
                        "option_quotes_available": bool(permissions.get("option_quotes_available")),
                        "iv_available": False,
                        "greeks_available": False,
                        "option_trade_risk": {"approved": False, "status": "blocked"},
                        "final_options_blocked_reason": "Option quotes, IV, and Greeks are unavailable; final option recommendations remain blocked.",
                    },
                    "error": None,
                },
            )
            checks["option_strategy_engine"] = _skipped(
                "local_option_strategy_engine",
                "Option strategy engine is available, but option quotes are unavailable; final options remain blocked.",
            )
    elif include_options:
        checks["option_risk"] = _skipped("local_option_risk", "Option risk check skipped because option quotes are unavailable.")
        checks["option_strategy_engine"] = _skipped("local_option_strategy_engine", "Option strategy check skipped because option quotes are unavailable.")

    if include_memory:
        memory_config = get_memory_config()
        if not memory_config.get("pinecone_configured"):
            checks["memory"] = _skipped("pinecone", "Pinecone memory is not configured.")
        else:
            checks["memory"] = _provider_call("pinecone", lambda: find_similar_setups({"ticker": normalized_ticker}, top_k=3))
    else:
        checks["memory"] = _skipped("pinecone", "Memory check was disabled.")

    for name, check in checks.items():
        if check.get("status") == "unavailable":
            warnings.append(f"{name} unavailable: {check.get('error')}")
        elif check.get("status") == "failed":
            errors.append(f"{name} failed: {check.get('error')}")

    market_data_payload = ((checks.get("market_data") or {}).get("data") or {}).get("data")
    if isinstance(market_data_payload, dict):
        quality = market_data_payload.get("data_quality")
        if isinstance(quality, dict):
            warnings.append(
                "market_data quality: "
                f"label={quality.get('quality_label')}, "
                f"quote_status={quality.get('quote_status')}, "
                f"price_source={quality.get('price_source')}"
            )
            warnings.extend(str(item) for item in quality.get("warnings", []) if item)
        bars = market_data_payload.get("bars")
        if isinstance(bars, list) and bars:
            candidate = {
                "ticker": normalized_ticker,
                "current_price": (market_data_payload.get("technical_snapshot") or {}).get("current_price"),
                "direction": "long",
            }
            checks["technical_confirmation"] = _provider_call(
                "local_technical_confirmation",
                lambda: {
                    "ok": True,
                    "ticker": normalized_ticker,
                    "source": "local",
                    "timestamp": _now_iso(),
                    "data": {
                        "volume_profile_confirmation": evaluate_volume_profile_confirmation(candidate, bars),
                        "timeframe_confirmation": evaluate_timeframe_confirmation(candidate, bars, weekly_history=None),
                    },
                    "error": None,
                },
            )
        else:
            checks["technical_confirmation"] = _skipped("local_technical_confirmation", "Historical bars are unavailable for technical confirmation.")

    return {
        "ok": not errors,
        "timestamp": _now_iso(),
        "ticker": normalized_ticker,
        "db_path": db_path,
        "selected_providers": {
            "market_data_provider": market_provider,
            "options_data_provider": options_provider,
        },
        "checks": checks,
        "startup_readiness": startup_readiness,
        "macro_risk": macro_risk,
        "database_readiness": startup_readiness.get("categories", {}).get("database_ready"),
        "provider_config_readiness": startup_readiness.get("categories", {}).get("providers_configured"),
        "options_blocked_status": startup_readiness.get("categories", {}).get("options_ready"),
        "safety_warnings": startup_readiness.get("warnings", []),
        "warnings": warnings + list(startup_readiness.get("warnings", [])),
        "errors": errors,
    }
