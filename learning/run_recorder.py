from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
import json
import os
import sqlite3

from db.schema_manager import apply_pending_migrations
from ideas.data_failures import split_data_failures

from .policy_registry import active_policy_defaults


RUN_RECORDER_VERSION = "research_run_recorder_v1"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _json(value: Any) -> str:
    return json.dumps(value if value is not None else {}, sort_keys=True, separators=(",", ":"))


def _load_json(value: Any, default: Any = None) -> Any:
    if value in (None, ""):
        return default
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return default


def _as_dict(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list:
    return value if isinstance(value, list) else []


def _safe_float(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _safe_int(value: Any) -> int | None:
    numeric = _safe_float(value)
    return int(numeric) if numeric is not None else None


def _recording_enabled(recording_enabled: bool | None = None) -> bool:
    if recording_enabled is not None:
        return bool(recording_enabled)
    return str(os.getenv("LEARNING_RECORDING_ENABLED", "true")).strip().lower() not in {"0", "false", "no", "off"}


def _row_to_dict(row: sqlite3.Row | None) -> dict | None:
    if row is None:
        return None
    payload = dict(row)
    for key in (
        "approved_plan_json",
        "execution_summary_json",
        "opportunity_components_json",
        "failed_constraints_json",
        "qualification_gaps_json",
        "data_quality_json",
        "market_regime_context_json",
        "source_market_data_timestamps_json",
        "raw_summary_json",
    ):
        if key in payload:
            payload[key] = _load_json(payload[key], {})
    return payload


def _requested_policy(db_path: str, policy_context: dict | None = None) -> dict:
    context = _as_dict(policy_context)
    active = active_policy_defaults(db_path)
    return {
        "policy_version": context.get("policy_version") or active.get("active_policy_version"),
        "policy_fingerprint": context.get("policy_fingerprint") or active.get("active_policy_fingerprint"),
        "policy": context.get("policy") or active.get("policy"),
    }


def _market_state(execution_result: dict) -> dict:
    assistant = _as_dict(execution_result.get("assistant_response"))
    return _as_dict(assistant.get("market_state"))


def _provider_status(execution_result: dict) -> str:
    state = _market_state(execution_result)
    status = state.get("provider_status")
    if status:
        return str(status)
    best = _as_dict(execution_result.get("best_available_ideas"))
    if best.get("ranking_status") == "unavailable":
        return "unavailable"
    if best.get("data_missing") or best.get("system_issues"):
        return "degraded"
    return "unknown"


def _data_status(execution_result: dict) -> str:
    best = _as_dict(execution_result.get("best_available_ideas"))
    ranking = str(best.get("ranking_status") or "")
    if ranking == "unavailable":
        return "unavailable"
    if best.get("data_missing") or best.get("system_issues"):
        return "degraded"
    return "available" if ranking == "available" else "unknown"


def _market_regime_label(execution_result: dict) -> str | None:
    state = _market_state(execution_result)
    regime = state.get("market_regime")
    if isinstance(regime, dict):
        return regime.get("label") or regime.get("regime") or regime.get("risk_level")
    return str(regime) if regime else None


def _source_market_timestamps(raw: dict) -> dict:
    timestamps = {}
    for key in ("timestamp", "created_at", "snapshot_at"):
        if raw.get(key):
            timestamps[key] = raw.get(key)
    for nested_key in ("data_freshness", "market_snapshot", "technical_snapshot", "data_quality"):
        nested = _as_dict(raw.get(nested_key))
        for key in ("latest_bar_timestamp", "timestamp", "as_of", "snapshot_at"):
            if nested.get(key):
                timestamps[f"{nested_key}.{key}"] = nested.get(key)
    return timestamps


def leakage_check(candidate: dict, snapshot_at: str) -> dict:
    warnings: list[str] = []
    errors: list[str] = []
    snapshot_text = str(snapshot_at or "")
    for field in ("published_at", "retrieved_at", "source_published_at"):
        value = candidate.get(field)
        if value and snapshot_text and str(value) > snapshot_text:
            errors.append(f"{field} occurs after snapshot_at; candidate is not point-in-time safe.")
    for source in _as_list(candidate.get("evidence_items")) + _as_list(candidate.get("sources")):
        if not isinstance(source, dict):
            continue
        published = source.get("published_at")
        if published and snapshot_text and str(published) > snapshot_text:
            errors.append("Evidence published after snapshot_at was detected.")
    return {"ok": not errors, "warnings": warnings, "errors": errors}


def _candidate_rows(best_ideas: dict) -> tuple[list[dict], dict]:
    rows: list[dict] = []
    diagnostics = {
        "paper_eligible_count": 0,
        "watchlist_count": 0,
        "blocked_count": 0,
        "option_count": 0,
        "option_underlying_watchlist_count": 0,
    }
    for bucket, label in (
        ("paper_eligible", "paper_eligible"),
        ("stock_watchlist", "watchlist"),
        ("option_research_only", "research_only"),
        ("blocked_but_interesting", "blocked"),
        ("option_underlying_watchlist", "option_underlying_watchlist"),
    ):
        for index, row in enumerate(_as_list(best_ideas.get(bucket)), start=1):
            if not isinstance(row, dict):
                continue
            candidate = dict(row)
            candidate.setdefault("actionability_status", label)
            candidate.setdefault("rank", row.get("rank") or index)
            candidate.setdefault("source_bucket", bucket)
            rows.append(candidate)
            if bucket == "paper_eligible":
                diagnostics["paper_eligible_count"] += 1
            elif bucket == "stock_watchlist":
                diagnostics["watchlist_count"] += 1
            elif bucket == "blocked_but_interesting":
                diagnostics["blocked_count"] += 1
            elif bucket == "option_research_only":
                diagnostics["option_count"] += 1
            elif bucket == "option_underlying_watchlist":
                diagnostics["option_underlying_watchlist_count"] += 1
    usable, failures = split_data_failures(rows)
    diagnostics["data_failure_count"] = len(failures)
    return usable, diagnostics


def _insert_execution_record(
    conn: sqlite3.Connection,
    *,
    execution_result: dict,
    approved_plan: dict,
    execution_summary: dict,
    policy_context: dict,
    root_run_id: str,
    pass_run_id: str | None,
    parent_run_id: str | None,
    request_id: str | None,
    plan_fingerprint: str | None,
    pass_number: int | None,
    adaptive_stop_reason: str | None,
    snapshot_at: str,
) -> int:
    cursor = conn.execute(
        """
        INSERT INTO research_execution_records (
            root_run_id, pass_run_id, parent_run_id, request_id, created_at, snapshot_at,
            plan_version, policy_version, policy_fingerprint, plan_fingerprint,
            requested_instrument, objective, approved_plan_json, execution_summary_json,
            market_regime_label, provider_status, data_status, pass_number, adaptive_stop_reason,
            paper_trading_only, brokerage_execution_enabled
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            root_run_id,
            pass_run_id,
            parent_run_id,
            request_id,
            _now_iso(),
            snapshot_at,
            approved_plan.get("plan_version"),
            policy_context.get("policy_version"),
            policy_context.get("policy_fingerprint"),
            plan_fingerprint,
            approved_plan.get("requested_instrument"),
            approved_plan.get("objective"),
            _json(approved_plan),
            _json(execution_summary),
            _market_regime_label(execution_result),
            _provider_status(execution_result),
            _data_status(execution_result),
            pass_number,
            adaptive_stop_reason,
            1,
            0,
        ),
    )
    return int(cursor.lastrowid)


def _snapshot_candidate(
    conn: sqlite3.Connection,
    *,
    execution_record_id: int,
    candidate: dict,
    policy_context: dict,
    root_run_id: str,
    pass_run_id: str | None,
    parent_run_id: str | None,
    request_id: str | None,
    plan_fingerprint: str | None,
    snapshot_at: str,
    source_pass: int | None,
    warnings: list[str],
) -> int | None:
    raw = _as_dict(candidate.get("raw_candidate")) or candidate
    leakage = leakage_check(raw, snapshot_at)
    if not leakage.get("ok"):
        warnings.extend(leakage.get("errors", []))
        return None

    asset_type = str(candidate.get("asset_type") or raw.get("asset_type") or "stock").lower()
    ticker = str(candidate.get("ticker") or raw.get("ticker") or raw.get("underlying_ticker") or "").upper()
    if not ticker:
        warnings.append("Skipped candidate snapshot without ticker.")
        return None
    actionability = (
        candidate.get("actionability_status")
        or candidate.get("status")
        or candidate.get("recommendation_status")
        or raw.get("recommendation_status")
        or raw.get("status")
        or candidate.get("source_bucket")
        or "unknown"
    )
    opportunity_components = (
        candidate.get("opportunity_components")
        or candidate.get("option_opportunity_components")
        or raw.get("opportunity_components")
        or raw.get("option_opportunity_components")
    )
    opportunity_score = (
        candidate.get("opportunity_score")
        if candidate.get("opportunity_score") is not None
        else candidate.get("option_opportunity_score")
    )
    opportunity_version = (
        candidate.get("opportunity_score_version")
        or candidate.get("option_opportunity_score_version")
        or raw.get("opportunity_score_version")
        or raw.get("option_opportunity_score_version")
    )
    data_confidence = candidate.get("data_confidence")
    if data_confidence is None:
        data_confidence = candidate.get("option_data_confidence")
    cursor = conn.execute(
        """
        INSERT INTO candidate_snapshots (
            execution_record_id, root_run_id, pass_run_id, parent_run_id, request_id,
            ticker, asset_type, option_contract, setup_type, scan_profile, direction,
            actionability_status, rank, engine_score, opportunity_score,
            opportunity_score_version, opportunity_components_json, data_confidence,
            entry_price, target_price, stop_loss, risk_reward, underlying_price,
            expiration, days_to_expiration, bid, ask, mid, failed_constraints_json,
            qualification_gaps_json, data_quality_json, market_regime_context_json,
            source_pass, snapshot_at, source_market_data_timestamps_json,
            policy_version, policy_fingerprint, plan_fingerprint, created_at, raw_summary_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            execution_record_id,
            root_run_id,
            pass_run_id,
            parent_run_id,
            request_id,
            ticker,
            asset_type,
            candidate.get("option_contract") or raw.get("option_contract"),
            candidate.get("setup_type") or candidate.get("setup") or raw.get("setup_type"),
            candidate.get("scan_profile") or raw.get("scan_profile"),
            candidate.get("direction") or raw.get("direction"),
            str(actionability),
            _safe_int(candidate.get("rank")),
            _safe_float(candidate.get("engine_score") if candidate.get("engine_score") is not None else candidate.get("score")),
            _safe_float(opportunity_score),
            opportunity_version,
            _json(opportunity_components),
            _safe_float(data_confidence),
            _safe_float(candidate.get("entry_price") if candidate.get("entry_price") is not None else raw.get("entry_price")),
            _safe_float(candidate.get("target_price") if candidate.get("target_price") is not None else raw.get("target_price")),
            _safe_float(candidate.get("stop_loss") if candidate.get("stop_loss") is not None else raw.get("stop_loss")),
            _safe_float(candidate.get("risk_reward") if candidate.get("risk_reward") is not None else raw.get("risk_reward")),
            _safe_float(candidate.get("underlying_price") if candidate.get("underlying_price") is not None else raw.get("underlying_price") or raw.get("current_price")),
            candidate.get("expiration") or raw.get("expiration"),
            _safe_int(candidate.get("days_to_expiration") if candidate.get("days_to_expiration") is not None else raw.get("days_to_expiration")),
            _safe_float(candidate.get("bid") if candidate.get("bid") is not None else raw.get("bid")),
            _safe_float(candidate.get("ask") if candidate.get("ask") is not None else raw.get("ask")),
            _safe_float(candidate.get("mid") if candidate.get("mid") is not None else raw.get("mid")),
            _json(candidate.get("failed_constraints") or raw.get("failed_constraints") or []),
            _json(candidate.get("qualification_gaps") or raw.get("qualification_gaps") or []),
            _json(candidate.get("data_quality") or raw.get("data_quality") or {}),
            _json(candidate.get("market_regime_context") or raw.get("market_regime_context") or {}),
            source_pass,
            snapshot_at,
            _json(_source_market_timestamps(raw)),
            policy_context.get("policy_version"),
            policy_context.get("policy_fingerprint"),
            plan_fingerprint,
            _now_iso(),
            _json(
                {
                    "source_bucket": candidate.get("source_bucket"),
                    "reason": candidate.get("reason") or raw.get("rejection_reason"),
                    "why_ranked": candidate.get("why_ranked"),
                    "key_risks": candidate.get("key_risks"),
                    "option_missing_requirements": candidate.get("missing_requirements"),
                }
            ),
        ),
    )
    return int(cursor.lastrowid)


def _record_single_execution(
    conn: sqlite3.Connection,
    execution_result: dict,
    db_path: str,
    policy_context: dict | None = None,
    *,
    root_run_id: str | None = None,
    pass_run_id: str | None = None,
    parent_run_id: str | None = None,
    pass_number: int | None = None,
    adaptive_stop_reason: str | None = None,
    plan_fingerprint: str | None = None,
    snapshot_at: str | None = None,
) -> dict:
    snapshot_at = snapshot_at or _now_iso()
    policy = _requested_policy(db_path, policy_context)
    approved = _as_dict(execution_result.get("approved_plan") or _as_dict(execution_result.get("policy_validation")).get("approved_plan"))
    execution_summary = _as_dict(execution_result.get("execution_summary"))
    root_run_id = root_run_id or str(execution_result.get("run_id") or execution_result.get("request_id") or pass_run_id or f"research-{snapshot_at}")
    pass_run_id = pass_run_id or str(execution_result.get("run_id") or root_run_id)
    request_id = approved.get("request_id") or execution_result.get("request_id")
    record_id = _insert_execution_record(
        conn,
        execution_result=execution_result,
        approved_plan=approved,
        execution_summary=execution_summary,
        policy_context=policy,
        root_run_id=root_run_id,
        pass_run_id=pass_run_id,
        parent_run_id=parent_run_id,
        request_id=request_id,
        plan_fingerprint=plan_fingerprint,
        pass_number=pass_number,
        adaptive_stop_reason=adaptive_stop_reason,
        snapshot_at=snapshot_at,
    )
    best_ideas = _as_dict(execution_result.get("best_available_ideas"))
    candidates, diagnostics = _candidate_rows(best_ideas)
    warnings: list[str] = []
    snapshot_ids: list[int] = []
    for candidate in candidates:
        snapshot_id = _snapshot_candidate(
            conn,
            execution_record_id=record_id,
            candidate=candidate,
            policy_context=policy,
            root_run_id=root_run_id,
            pass_run_id=pass_run_id,
            parent_run_id=parent_run_id,
            request_id=request_id,
            plan_fingerprint=plan_fingerprint,
            snapshot_at=snapshot_at,
            source_pass=pass_number or _safe_int(candidate.get("source_pass")),
            warnings=warnings,
        )
        if snapshot_id is not None:
            snapshot_ids.append(snapshot_id)
    return {
        "execution_record_id": record_id,
        "candidate_snapshot_ids": snapshot_ids,
        "snapshots_created": len(snapshot_ids),
        "diagnostics": diagnostics,
        "warnings": warnings,
    }


def record_research_execution(
    execution_result: dict,
    db_path: str = "strategy_library.db",
    policy_context: dict | None = None,
    recording_enabled: bool | None = None,
) -> dict:
    if not _recording_enabled(recording_enabled):
        return {"ok": True, "recording_version": RUN_RECORDER_VERSION, "recording_enabled": False, "records_created": 0, "candidate_snapshots_created": 0, "warnings": [], "errors": []}
    try:
        apply_pending_migrations(db_path)
        with _connect(db_path) as conn:
            result = _record_single_execution(conn, _as_dict(execution_result), db_path, policy_context)
        return {
            "ok": True,
            "recording_version": RUN_RECORDER_VERSION,
            "recording_enabled": True,
            "records_created": 1,
            "candidate_snapshots_created": result["snapshots_created"],
            "execution_record_ids": [result["execution_record_id"]],
            "candidate_snapshot_ids": result["candidate_snapshot_ids"],
            "diagnostics": result["diagnostics"],
            "warnings": result["warnings"],
            "errors": [],
        }
    except Exception as exc:
        return {"ok": False, "recording_version": RUN_RECORDER_VERSION, "recording_enabled": True, "records_created": 0, "candidate_snapshots_created": 0, "warnings": [f"Learning recorder failed: {exc}"], "errors": [str(exc)]}


def record_adaptive_research_execution(
    adaptive_result: dict,
    db_path: str = "strategy_library.db",
    policy_context: dict | None = None,
    recording_enabled: bool | None = None,
) -> dict:
    if not _recording_enabled(recording_enabled):
        return {"ok": True, "recording_version": RUN_RECORDER_VERSION, "recording_enabled": False, "records_created": 0, "candidate_snapshots_created": 0, "warnings": [], "errors": []}
    try:
        apply_pending_migrations(db_path)
        root_run_id = str(adaptive_result.get("root_run_id") or adaptive_result.get("request_id") or f"adaptive-{_now_iso()}")
        snapshot_at = _now_iso()
        execution_record_ids: list[int] = []
        candidate_snapshot_ids: list[int] = []
        warnings: list[str] = []
        with _connect(db_path) as conn:
            for pass_result in _as_list(adaptive_result.get("passes")):
                execution_result = _as_dict(pass_result.get("execution_result"))
                if not execution_result:
                    continue
                recorded = _record_single_execution(
                    conn,
                    execution_result,
                    db_path,
                    policy_context,
                    root_run_id=root_run_id,
                    pass_run_id=pass_result.get("run_id"),
                    parent_run_id=pass_result.get("parent_run_id"),
                    pass_number=_safe_int(pass_result.get("pass_number")),
                    adaptive_stop_reason=adaptive_result.get("stop_reason"),
                    plan_fingerprint=pass_result.get("plan_fingerprint"),
                    snapshot_at=snapshot_at,
                )
                execution_record_ids.append(recorded["execution_record_id"])
                candidate_snapshot_ids.extend(recorded["candidate_snapshot_ids"])
                warnings.extend(recorded["warnings"])
            if adaptive_result.get("consolidated_result"):
                consolidated_execution = {
                    "request_id": adaptive_result.get("request_id"),
                    "run_id": f"{root_run_id}:consolidated",
                    "approved_plan": _as_dict(_as_dict(adaptive_result.get("initial_policy_validation")).get("approved_plan")),
                    "execution_summary": {
                        "status": adaptive_result.get("status"),
                        "adaptive_consolidated": True,
                        "passes_executed": adaptive_result.get("passes_executed"),
                        "refinement_used": adaptive_result.get("refinement_used"),
                    },
                    "trading_result": adaptive_result.get("consolidated_result"),
                    "best_available_ideas": adaptive_result.get("best_available_ideas"),
                    "assistant_response": adaptive_result.get("assistant_response"),
                }
                recorded = _record_single_execution(
                    conn,
                    consolidated_execution,
                    db_path,
                    policy_context,
                    root_run_id=root_run_id,
                    pass_run_id=f"{root_run_id}:consolidated",
                    parent_run_id=root_run_id,
                    pass_number=0,
                    adaptive_stop_reason=adaptive_result.get("stop_reason"),
                    plan_fingerprint=None,
                    snapshot_at=snapshot_at,
                )
                execution_record_ids.append(recorded["execution_record_id"])
                candidate_snapshot_ids.extend(recorded["candidate_snapshot_ids"])
                warnings.extend(recorded["warnings"])
        return {
            "ok": True,
            "recording_version": RUN_RECORDER_VERSION,
            "recording_enabled": True,
            "records_created": len(execution_record_ids),
            "candidate_snapshots_created": len(candidate_snapshot_ids),
            "execution_record_ids": execution_record_ids,
            "candidate_snapshot_ids": candidate_snapshot_ids,
            "warnings": list(dict.fromkeys(warnings)),
            "errors": [],
        }
    except Exception as exc:
        return {"ok": False, "recording_version": RUN_RECORDER_VERSION, "recording_enabled": True, "records_created": 0, "candidate_snapshots_created": 0, "warnings": [f"Learning recorder failed: {exc}"], "errors": [str(exc)]}


def get_snapshot_counts(db_path: str = "strategy_library.db") -> dict:
    try:
        apply_pending_migrations(db_path)
        with _connect(db_path) as conn:
            candidate_count = conn.execute("SELECT COUNT(*) FROM candidate_snapshots").fetchone()[0]
            execution_count = conn.execute("SELECT COUNT(*) FROM research_execution_records").fetchone()[0]
            outcome_count = conn.execute("SELECT COUNT(*) FROM candidate_forward_outcomes").fetchone()[0]
            pending_count = conn.execute(
                """
                SELECT COUNT(*)
                FROM candidate_snapshots s
                WHERE NOT EXISTS (
                    SELECT 1 FROM candidate_forward_outcomes o
                    WHERE o.candidate_snapshot_id = s.id
                )
                """
            ).fetchone()[0]
        return {
            "ok": True,
            "execution_record_count": execution_count,
            "candidate_snapshot_count": candidate_count,
            "mature_outcome_count": outcome_count,
            "pending_outcome_count": pending_count,
            "errors": [],
        }
    except sqlite3.Error as exc:
        return {"ok": False, "execution_record_count": 0, "candidate_snapshot_count": 0, "mature_outcome_count": 0, "pending_outcome_count": 0, "errors": [str(exc)]}
