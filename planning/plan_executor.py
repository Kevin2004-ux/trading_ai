from __future__ import annotations

from copy import deepcopy
from typing import Any
from uuid import uuid4

from agent.trading_brain import run_weekly_trade_hunt
from discovery import (
    DEFAULT_DISCOVERY_SOURCES,
    MAX_DISCOVERED_TICKERS,
    discover_candidates,
    empty_discovery_result,
    summarize_discovery_result,
)
from ideas import build_assistant_trade_response, build_best_available_ideas, format_best_ideas_response
from learning import active_policy_defaults, record_research_execution
from research.research_orchestrator import build_current_research, empty_research_response, scopes_from_research_preferences
from scanner.options_discovery import discover_option_ideas, empty_option_discovery_response
from scanner.universe_builder import get_default_universe, validate_ticker_universe

from .policy_validator import POLICY_VERSION, validate_scan_plan
from .scan_plan import ScanPlan


EXECUTION_VERSION = "scan_plan_executor_v1"


def _as_dict(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list:
    return value if isinstance(value, list) else []


def _control_float(controls: dict, key: str, default: float) -> float:
    try:
        return float(controls.get(key, default))
    except (TypeError, ValueError):
        return default


def _control_int(controls: dict, key: str, default: int) -> int:
    try:
        return int(controls.get(key, default))
    except (TypeError, ValueError):
        return default


def _empty_execution_summary() -> dict:
    return {
        "status": "failed",
        "universes_requested": [],
        "universes_used": [],
        "ticker_count_before_deduplication": 0,
        "ticker_count_after_deduplication": 0,
        "ticker_count_executed": 0,
        "profiles_run": [],
        "include_options": False,
        "options_final_eligibility": False,
        "partial_results": False,
        "auto_log": False,
        "effective_direction": "long",
        "unapplied_preferences": [],
    }


def _empty_universe_result(universes: list[str] | None = None) -> dict:
    return {
        "ok": False,
        "universes_requested": universes or [],
        "universes_loaded": [],
        "tickers": [],
        "count": 0,
        "source": "scan_plan_combined",
        "truncated": False,
        "warnings": [],
        "errors": [],
    }


def _base_response(
    *,
    policy_validation: dict,
    db_path: str,
    run_id: str | None,
) -> dict:
    return {
        "ok": False,
        "execution_version": EXECUTION_VERSION,
        "paper_trading_only": True,
        "brokerage_execution_enabled": False,
        "request_id": _as_dict(policy_validation.get("approved_plan")).get("request_id"),
        "run_id": run_id,
        "policy_validation": policy_validation,
        "proposed_plan": policy_validation.get("proposed_plan", {}),
        "approved_plan": policy_validation.get("approved_plan", {}),
        "execution_config": policy_validation.get("execution_config", {}),
        "universe_result": _empty_universe_result(),
        "discovery_result": empty_discovery_result(),
        "discovery_summary": summarize_discovery_result(empty_discovery_result()),
        "execution_summary": _empty_execution_summary(),
        "trading_result": {},
        "option_discovery": empty_option_discovery_response(requested=False, reason="Option discovery was not requested."),
        "best_available_ideas": {},
        "research": empty_research_response(status="disabled", provider="none", request_id=run_id, warnings=["Current research was not requested."]),
        "assistant_response": {},
        "formatted_response": "",
        "active_policy_version": None,
        "active_policy_fingerprint": None,
        "learning_recording": {},
        "warnings": list(_as_list(policy_validation.get("warnings"))),
        "errors": list(_as_list(policy_validation.get("errors"))),
    }


def _dedupe_tickers(tickers: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for raw in tickers:
        ticker = str(raw or "").strip().upper()
        if not ticker or ticker in seen:
            continue
        seen.add(ticker)
        result.append(ticker)
    return result


def _control_list(controls: dict, key: str, default: list[str]) -> list[str]:
    value = controls.get(key)
    if not isinstance(value, list):
        return list(default)
    return [str(item) for item in value if str(item or "").strip()]


def build_combined_universe(execution_config: dict) -> dict:
    universes = list(_as_list(execution_config.get("universes")))
    max_tickers = int(execution_config.get("max_tickers") or 100)
    custom_tickers = list(_as_list(execution_config.get("custom_tickers")))
    result = _empty_universe_result(universes)
    combined: list[str] = []
    before_dedup = 0

    for universe in universes:
        normalized = str(universe or "").strip().lower()
        if normalized == "custom":
            validated = validate_ticker_universe(custom_tickers, max_tickers=max_tickers)
            if not validated.get("ok"):
                result["warnings"].extend(validated.get("errors", []))
                continue
            tickers = validated.get("tickers", [])
            result["universes_loaded"].append("custom")
        else:
            loaded = get_default_universe(normalized, max_tickers=max_tickers)
            if not loaded.get("ok"):
                result["warnings"].extend(loaded.get("errors", []) or [loaded.get("error", f"Failed to load universe: {normalized}")])
                continue
            tickers = loaded.get("tickers", [])
            result["universes_loaded"].append(normalized)
        before_dedup += len(tickers)
        combined.extend(tickers)

    deduped = _dedupe_tickers(combined)
    truncated = len(deduped) > max_tickers
    if truncated:
        deduped = deduped[:max_tickers]
        result["warnings"].append(f"Combined universe exceeded max_tickers={max_tickers} and was truncated.")

    result.update(
        {
            "ok": bool(deduped),
            "tickers": deduped,
            "count": len(deduped),
            "ticker_count_before_deduplication": before_dedup,
            "ticker_count_after_deduplication": len(deduped),
            "truncated": truncated,
        }
    )
    if not deduped:
        result["errors"].append("No valid tickers remained after combining approved universes.")
    return result


def _is_broad_discovery_plan(approved_plan: dict, execution_config: dict, controls: dict) -> bool:
    if not controls.get("use_dynamic_discovery"):
        return False
    objective = str(approved_plan.get("objective") or "best_ideas").lower()
    if objective == "ticker_review" or approved_plan.get("custom_tickers") or execution_config.get("custom_tickers"):
        return False
    return objective in {"best_ideas", "watchlist", "options_research"}


def _max_discovered_tickers(controls: dict, execution_config: dict) -> int:
    default = int(execution_config.get("max_tickers") or 20)
    return max(1, min(_control_int(controls, "max_discovered_tickers", default), MAX_DISCOVERED_TICKERS))


def _discovery_bypass_reason(approved_plan: dict, execution_config: dict, controls: dict) -> str | None:
    objective = str(approved_plan.get("objective") or "best_ideas").lower()
    if objective == "ticker_review":
        return "explicit_ticker_scope"
    if approved_plan.get("custom_tickers") or execution_config.get("custom_tickers"):
        return "custom_ticker_scope"
    if not controls.get("use_dynamic_discovery"):
        return "not_requested"
    if objective not in {"best_ideas", "watchlist", "options_research"}:
        return "unsupported_objective"
    return None


def _build_execution_universe(
    *,
    approved_plan: dict,
    execution_config: dict,
    controls: dict,
    db_path: str,
) -> tuple[dict, dict]:
    bypass_reason = _discovery_bypass_reason(approved_plan, execution_config, controls)
    if bypass_reason:
        return build_combined_universe(execution_config), empty_discovery_result(bypass_reason=bypass_reason)

    max_discovered = _max_discovered_tickers(controls, execution_config)
    discovery_result = discover_candidates(
        db_path=db_path,
        requested_sources=_control_list(controls, "discovery_sources", DEFAULT_DISCOVERY_SOURCES),
        max_tickers=max_discovered,
    )
    discovered_tickers = _as_list(discovery_result.get("tickers"))
    validated = validate_ticker_universe(discovered_tickers, max_tickers=max_discovered)
    if validated.get("ok"):
        warnings = list(_as_list(discovery_result.get("warnings"))) + list(_as_list(validated.get("errors")))
        discovery_result = {
            **discovery_result,
            "tickers": validated.get("tickers", []),
            "discovered_count": len(validated.get("tickers", [])),
            "discovery_used": True,
            "fallback_used": False,
            "bypass_reason": None,
            "max_discovered_tickers": max_discovered,
        }
        universe_result = {
            "ok": True,
            "universes_requested": list(_as_list(execution_config.get("universes"))),
            "universes_loaded": ["dynamic_discovery"],
            "tickers": validated.get("tickers", []),
            "count": len(validated.get("tickers", [])),
            "source": "dynamic_discovery",
            "ticker_count_before_deduplication": discovery_result.get("discovered_count", 0),
            "ticker_count_after_deduplication": len(validated.get("tickers", [])),
            "truncated": len(discovered_tickers) > len(validated.get("tickers", [])),
            "warnings": warnings,
            "errors": [],
            "discovery_result": discovery_result,
        }
        return universe_result, discovery_result

    fallback = build_combined_universe(execution_config)
    discovery_result = {
        **discovery_result,
        "discovery_used": False,
        "fallback_used": True,
        "bypass_reason": None,
        "max_discovered_tickers": max_discovered,
    }
    fallback["warnings"] = list(_as_list(fallback.get("warnings"))) + list(_as_list(discovery_result.get("warnings"))) + [
        "Dynamic discovery returned no valid tickers; falling back to the approved combined universe."
    ]
    fallback["discovery_result"] = discovery_result
    return fallback, discovery_result


def _unapplied_preferences(approved_plan: dict, execution_config: dict, proposed_plan: dict | None = None) -> list[dict]:
    rows: list[dict] = []
    proposed_soft = _as_dict(_as_dict(proposed_plan).get("soft_adjustments"))
    profile_weights = _as_dict(proposed_soft.get("profile_weights"))
    if profile_weights:
        rows.append(
            {
                "field": "profile_weights",
                "value": execution_config.get("profile_weights"),
                "reason": "Current scanner has no safe profile-weight interface; weights were not applied to hard profile constraints or eligibility.",
            }
        )
    soft = _as_dict(execution_config.get("soft_scanner_preferences"))
    for key in ("minimum_relative_volume", "breakout_proximity_percent", "pullback_distance_percent"):
        if soft.get(key) is not None:
            rows.append(
                {
                    "field": key,
                    "value": soft.get(key),
                    "reason": "Soft scanner preference was not mapped to hard scanner/profile thresholds in this task.",
                }
            )
    refinement = _as_dict(approved_plan.get("refinement"))
    if (refinement.get("max_passes") or 1) > 1:
        rows.append(
            {
                "field": "refinement.max_passes",
                "value": refinement.get("max_passes"),
                "reason": "Autonomous refinement passes are preserved for audit but not invoked in Task 5.",
            }
        )
    return rows


def _apply_minimum_opportunity_filter(best_ideas: dict, minimum_score: float | None) -> None:
    if minimum_score is None:
        return
    best_ideas["minimum_opportunity_score"] = minimum_score
    best_ideas["minimum_opportunity_score_note"] = "Applied to research display buckets only; paper-eligible ideas and strict statuses were not changed."
    for bucket in ("stock_watchlist", "blocked_but_interesting"):
        filtered = []
        hidden = []
        for row in _as_list(best_ideas.get(bucket)):
            if str(row.get("asset_type", "stock")).lower() == "option":
                filtered.append(row)
                continue
            score = row.get("opportunity_score")
            try:
                numeric = float(score)
            except (TypeError, ValueError):
                numeric = None
            if numeric is not None and numeric < minimum_score:
                hidden.append(row)
            else:
                filtered.append(row)
        best_ideas[bucket] = filtered
        if hidden:
            best_ideas.setdefault("plan_filtered_research_rows", []).extend(
                {"ticker": row.get("ticker"), "bucket": bucket, "opportunity_score": row.get("opportunity_score")}
                for row in hidden
            )


def _execution_status(trading_result: dict, best_ideas: dict, errors: list[str], warnings: list[str]) -> str:
    if errors:
        return "failed"
    if best_ideas.get("ranking_status") == "unavailable":
        return "unavailable"
    if not trading_result.get("ok"):
        return "failed"
    return "completed_with_warnings" if warnings or trading_result.get("errors") else "completed"


def _stock_candidates_for_option_discovery(best_ideas: dict) -> list[dict]:
    rows: list[dict] = []
    rows.extend(item for item in _as_list(best_ideas.get("paper_eligible")) if isinstance(item, dict) and str(item.get("asset_type", "stock")).lower() != "option")
    rows.extend(item for item in _as_list(best_ideas.get("stock_watchlist")) if isinstance(item, dict))
    rows.extend(item for item in _as_list(best_ideas.get("blocked_but_interesting")) if isinstance(item, dict) and str(item.get("asset_type", "stock")).lower() != "option")
    return rows


def _run_option_discovery(
    *,
    include_options: bool,
    approved_plan: dict,
    execution_config: dict,
    stock_only_best_ideas: dict,
    runtime_context: dict | None,
) -> dict:
    if not include_options:
        return empty_option_discovery_response(requested=False, reason="Option discovery disabled for stock-only request.")

    option_preferences = _as_dict(approved_plan.get("option_preferences"))
    explicit_tickers = None
    if str(approved_plan.get("objective") or "").lower() == "ticker_review":
        explicit_tickers = [str(item).upper() for item in _as_list(approved_plan.get("custom_tickers")) if str(item).strip()]

    discovery_context = {
        **_as_dict(runtime_context),
        "requested": True,
        "safe_to_run_options": bool(execution_config.get("options_final_eligibility")),
        "options_final_eligibility": bool(execution_config.get("options_final_eligibility")),
        "requested_instrument": approved_plan.get("requested_instrument"),
    }
    return discover_option_ideas(
        _stock_candidates_for_option_discovery(stock_only_best_ideas),
        explicit_tickers=explicit_tickers,
        option_preferences=option_preferences,
        runtime_context=discovery_context,
        max_underlyings=5,
        max_contracts_per_ticker=int(execution_config.get("max_option_contracts_per_trade") or option_preferences.get("max_contracts_per_ticker") or 3),
    )


def _research_candidate_context(assistant_response: dict, max_tickers: int) -> tuple[list[str], list[dict]]:
    tickers: list[str] = []
    context: list[dict] = []
    for row in _as_list(assistant_response.get("top_stocks")) + _as_list(assistant_response.get("top_options")):
        if not isinstance(row, dict):
            continue
        ticker = str(row.get("ticker") or "").strip().upper()
        if not ticker or ticker in tickers:
            continue
        tickers.append(ticker)
        context.append(
            {
                "ticker": ticker,
                "asset_type": row.get("asset_type"),
                "status": row.get("status"),
                "rank": row.get("rank"),
                "setup": row.get("setup") or row.get("strategy"),
                "opportunity_score": row.get("opportunity_score"),
            }
        )
        if len(tickers) >= max_tickers:
            break
    return tickers, context


def _research_max_tickers() -> int:
    try:
        return max(1, min(20, int(__import__("os").getenv("OPENAI_RESEARCH_MAX_TICKERS", "3"))))
    except (TypeError, ValueError):
        return 3


def _run_current_research_if_requested(approved_plan: dict, assistant_response: dict, run_id: str, warnings: list[str]) -> dict:
    scopes = scopes_from_research_preferences(_as_dict(approved_plan.get("research_preferences")))
    if not scopes:
        return empty_research_response(
            status="disabled",
            provider="none",
            request_id=run_id,
            scopes=[],
            warnings=["Current research was not requested."],
        )

    max_tickers = _research_max_tickers()
    tickers, context = _research_candidate_context(assistant_response, max_tickers=max_tickers)
    if not tickers and str(approved_plan.get("objective")) == "ticker_review":
        tickers = [str(item).upper() for item in _as_list(approved_plan.get("custom_tickers")) if str(item).strip()]
        context = [{"ticker": ticker, "asset_type": "stock", "status": "ticker_review"} for ticker in tickers]
    if not tickers:
        warnings.append("Current research was requested, but no legitimate ranked tickers were available for broad research.")
        return empty_research_response(
            status="unavailable",
            provider="none",
            request_id=run_id,
            scopes=scopes,
            warnings=["No legitimate ranked tickers were available for current research."],
        )

    return build_current_research(
        tickers,
        scopes=scopes,
        candidate_context=context,
        request_id=run_id,
    )


def execute_scan_plan(
    proposed_plan: ScanPlan | dict,
    runtime_context: dict | None = None,
    db_path: str = "strategy_library.db",
    internal_controls: dict | None = None,
) -> dict:
    policy_validation = validate_scan_plan(proposed_plan, runtime_context=runtime_context)
    run_id = _as_dict(policy_validation.get("approved_plan")).get("request_id") or str(uuid4())
    response = _base_response(policy_validation=policy_validation, db_path=db_path, run_id=run_id)
    approved_plan = _as_dict(policy_validation.get("approved_plan"))
    execution_config = _as_dict(policy_validation.get("execution_config"))
    controls = _as_dict(internal_controls)
    run_option_discovery = bool(controls.get("run_option_discovery", True))
    run_current_research = bool(controls.get("run_current_research", True))
    record_learning = bool(controls.get("record_learning", True))
    warnings = response["warnings"]
    errors = response["errors"]
    active_policy = active_policy_defaults(db_path)
    response["active_policy_version"] = active_policy.get("active_policy_version")
    response["active_policy_fingerprint"] = active_policy.get("active_policy_fingerprint")
    if active_policy.get("errors"):
        warnings.extend(str(item) for item in active_policy.get("errors", []))

    if not policy_validation.get("ok"):
        response["execution_summary"]["status"] = "failed"
        response["formatted_response"] = "ScanPlan validation failed; no scan was executed."
        return response

    effective_direction = str(approved_plan.get("direction") or "long").lower()
    if effective_direction in {"short", "both"}:
        warnings.append(f"Direction '{effective_direction}' is not fully supported by the current scanner; executing long-only research.")
        effective_direction = "long"

    universe_result, discovery_result = _build_execution_universe(
        approved_plan=approved_plan,
        execution_config=execution_config,
        controls=controls,
        db_path=db_path,
    )
    response["universe_result"] = universe_result
    response["discovery_result"] = discovery_result
    response["discovery_summary"] = summarize_discovery_result(discovery_result)
    if universe_result.get("warnings"):
        warnings.extend(str(item) for item in universe_result.get("warnings", []))
    if not universe_result.get("ok"):
        errors.extend(str(item) for item in universe_result.get("errors", []))
        response["execution_summary"].update(
            {
                "status": "failed",
                "universes_requested": universe_result.get("universes_requested", []),
                "universes_used": universe_result.get("universes_loaded", []),
                "ticker_count_before_deduplication": universe_result.get("ticker_count_before_deduplication", 0),
                "ticker_count_after_deduplication": 0,
                "ticker_count_executed": 0,
                "profiles_run": execution_config.get("profiles", []),
                "include_options": bool(execution_config.get("include_options")),
                "options_final_eligibility": bool(execution_config.get("options_final_eligibility")),
                "auto_log": False,
                "effective_direction": effective_direction,
                "discovery_summary": response["discovery_summary"],
                "unapplied_preferences": _unapplied_preferences(approved_plan, execution_config, policy_validation.get("proposed_plan")),
            }
        )
        response["errors"] = list(dict.fromkeys(errors))
        return response

    trading_result = run_weekly_trade_hunt(
        universe="scan_plan_combined",
        max_tickers=int(execution_config.get("max_tickers") or universe_result.get("count", 0)),
        profiles=list(_as_list(execution_config.get("profiles"))),
        max_trades=int(execution_config.get("max_trades") or 0),
        min_trades=int(execution_config.get("min_trades") or 0),
        include_catalysts=bool(execution_config.get("include_catalysts")),
        include_market_regime=bool(execution_config.get("include_market_regime")),
        include_relative_strength=bool(execution_config.get("include_relative_strength")),
        include_research_briefs=False,
        include_options=bool(execution_config.get("include_options")),
        prefer_options=bool(execution_config.get("prefer_options")),
        max_option_contracts_per_trade=int(execution_config.get("max_option_contracts_per_trade") or 3),
        include_portfolio_risk=bool(execution_config.get("include_portfolio_risk")),
        include_position_sizing=bool(execution_config.get("include_position_sizing")),
        include_memory_context=True,
        store_memory=False,
        auto_log=False,
        db_path=db_path,
        tickers=universe_result.get("tickers", []),
        scan_max_concurrency=_control_int(controls, "scan_max_concurrency", 5),
        scan_ticker_timeout_seconds=_control_float(controls, "scan_ticker_timeout_seconds", 15.0),
        scan_total_timeout_seconds=_control_float(controls, "scan_total_timeout_seconds", 180.0),
        universe_result_override={
            "ok": True,
            "universe": "scan_plan_combined",
            "tickers": universe_result.get("tickers", []),
            "count": universe_result.get("count", 0),
            "source": universe_result.get("source") or "scan_plan_combined",
            "errors": [],
            "warnings": universe_result.get("warnings", []),
            "discovery_result": discovery_result if universe_result.get("source") == "dynamic_discovery" else None,
            "discovery_summary": response["discovery_summary"],
        },
        max_total_candidates=int(execution_config.get("max_candidates") or 20),
        scanner_config={
            "plan_executor": True,
            "execution_version": EXECUTION_VERSION,
        },
    )
    response["trading_result"] = trading_result if isinstance(trading_result, dict) else {}
    response["trading_result"]["discovery_result"] = discovery_result
    response["trading_result"]["discovery_summary"] = response["discovery_summary"]

    opportunity_weights = _as_dict(execution_config.get("opportunity_weights")) or _as_dict(_as_dict(active_policy.get("policy")).get("stock_opportunity_weights"))
    stock_only_best_ideas = build_best_available_ideas(
        response["trading_result"],
        config={
            "include_options": False,
            "opportunity_ranker": {"weights": opportunity_weights} if opportunity_weights else {},
        },
    )
    option_discovery = (
        _run_option_discovery(
            include_options=bool(execution_config.get("include_options")),
            approved_plan=approved_plan,
            execution_config=execution_config,
            stock_only_best_ideas=stock_only_best_ideas,
            runtime_context=runtime_context,
        )
        if run_option_discovery
        else empty_option_discovery_response(
            requested=bool(execution_config.get("include_options")),
            reason="Option discovery was deferred by adaptive execution.",
        )
    )
    response["option_discovery"] = option_discovery
    response["trading_result"]["option_discovery"] = option_discovery

    best_ideas = build_best_available_ideas(
        response["trading_result"],
        config={
            "include_options": bool(execution_config.get("include_options")),
            "option_discovery": option_discovery,
            "opportunity_ranker": {"weights": opportunity_weights} if opportunity_weights else {},
        },
    )
    if best_ideas.get("ranking_status") == "unavailable":
        warnings.extend(str(item) for item in _as_list(best_ideas.get("system_issues")) if item)
        warnings.extend(str(item) for item in _as_list(best_ideas.get("data_missing")) if item)
    minimum_score = _as_dict(execution_config.get("soft_scanner_preferences")).get("minimum_opportunity_score")
    _apply_minimum_opportunity_filter(best_ideas, minimum_score)
    assistant_response = build_assistant_trade_response(
        best_ideas,
        trading_result=response["trading_result"],
        requested_instrument=approved_plan.get("requested_instrument", "auto"),
        run_id=run_id,
    )
    assistant_response.setdefault("scan_summary", {})["active_policy_version"] = response["active_policy_version"]
    research = (
        _run_current_research_if_requested(approved_plan, assistant_response, run_id, warnings)
        if run_current_research
        else empty_research_response(
            status="disabled",
            provider="none",
            request_id=run_id,
            warnings=["Current research was deferred by adaptive execution."],
        )
    )
    assistant_response = build_assistant_trade_response(
        best_ideas,
        trading_result=response["trading_result"],
        requested_instrument=approved_plan.get("requested_instrument", "auto"),
        run_id=run_id,
        research=research,
    )
    assistant_response.setdefault("scan_summary", {})["active_policy_version"] = response["active_policy_version"]
    assistant_response.setdefault("scan_summary", {})["active_policy_fingerprint"] = response["active_policy_fingerprint"]
    formatted = format_best_ideas_response(assistant_response)

    response["best_available_ideas"] = best_ideas
    response["research"] = research
    response["assistant_response"] = assistant_response
    response["formatted_response"] = formatted

    scan_execution = _as_dict(response["trading_result"].get("scan_execution_summary"))
    partial_results = bool(scan_execution.get("partial_results_used"))
    unapplied = _unapplied_preferences(approved_plan, execution_config, policy_validation.get("proposed_plan"))
    if unapplied:
        warnings.append("Some ScanPlan preferences were preserved for audit but not applied to hard scanner behavior.")

    errors.extend(str(item) for item in _as_list(response["trading_result"].get("errors")) if item)
    status = _execution_status(response["trading_result"], best_ideas, [], warnings)
    if errors and best_ideas.get("ranking_status") != "unavailable":
        status = "completed_with_warnings" if response["trading_result"].get("ok") else "failed"
    elif best_ideas.get("ranking_status") == "unavailable":
        status = "unavailable"

    response["execution_summary"].update(
        {
            "status": status,
            "universes_requested": universe_result.get("universes_requested", []),
            "universes_used": universe_result.get("universes_loaded", []),
            "ticker_count_before_deduplication": universe_result.get("ticker_count_before_deduplication", 0),
            "ticker_count_after_deduplication": universe_result.get("ticker_count_after_deduplication", 0),
            "ticker_count_executed": universe_result.get("count", 0),
            "profiles_run": response["trading_result"].get("summary", {}).get("profiles_run") or execution_config.get("profiles", []),
            "include_options": bool(execution_config.get("include_options")),
            "options_final_eligibility": bool(execution_config.get("options_final_eligibility")),
            "partial_results": partial_results,
            "auto_log": False,
            "effective_direction": effective_direction,
            "unapplied_preferences": unapplied,
            "discovery_used": universe_result.get("source") == "dynamic_discovery",
            "discovery_summary": response["discovery_summary"],
        }
    )
    response["warnings"] = list(dict.fromkeys(str(item) for item in warnings if item))
    response["errors"] = list(dict.fromkeys(str(item) for item in errors if item))
    response["ok"] = status in {"completed", "completed_with_warnings", "unavailable"}
    if record_learning:
        recording = record_research_execution(
            response,
            db_path=db_path,
            policy_context={
                "policy_version": response["active_policy_version"],
                "policy_fingerprint": response["active_policy_fingerprint"],
                "policy": active_policy.get("policy"),
            },
        )
        response["learning_recording"] = recording
        if not recording.get("ok"):
            response["warnings"].extend(str(item) for item in recording.get("warnings", []))
            response["warnings"] = list(dict.fromkeys(response["warnings"]))
    return response
