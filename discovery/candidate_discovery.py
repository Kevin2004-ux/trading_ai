from __future__ import annotations

import json
import os
from pathlib import Path
import sqlite3
from typing import Any

from scanner.universe_builder import validate_ticker_universe

from .fallback_universe import DEFAULT_FALLBACK_UNIVERSES, discover_liquid_fallback_candidates
from .source_models import DISCOVERY_VERSION, MAX_DISCOVERED_TICKERS, DiscoveryCandidate, empty_discovery_result, safe_float, unique_texts, utc_now_iso


DEFAULT_DISCOVERY_SOURCES = ["manual_hotlist", "database_recent", "liquid_fallback"]


def _bounded_int(value: Any, default: int, minimum: int = 1, maximum: int = 100) -> int:
    try:
        numeric = int(value)
    except (TypeError, ValueError):
        numeric = default
    return max(minimum, min(numeric, maximum))


def _deserialize_json(value: Any) -> Any:
    if value is None or not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def discover_manual_hotlist_candidates(
    *,
    max_tickers: int,
    discovered_at: str,
    env_value: str | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    raw_value = os.getenv("DISCOVERY_MANUAL_HOTLIST") if env_value is None else env_value
    if not raw_value:
        return [], []

    raw_tickers = [item.strip() for item in str(raw_value).split(",")]
    validated = validate_ticker_universe(raw_tickers, max_tickers=max_tickers)
    warnings = [str(item) for item in validated.get("errors", []) if item]
    rows: list[DiscoveryCandidate] = []
    for index, ticker in enumerate(validated.get("tickers", [])):
        rows.append(
            DiscoveryCandidate(
                ticker=ticker,
                source="DISCOVERY_MANUAL_HOTLIST",
                source_type="manual_hotlist",
                discovered_at=discovered_at,
                as_of=discovered_at,
                discovery_score=max(85.0, 98.0 - index),
                reasons=["Manually supplied discovery hotlist ticker."],
                warnings=[],
                raw_metadata={"position": index + 1},
                point_in_time_safe=True,
                requires_live_validation=True,
            )
        )
    return [row.to_dict() for row in rows], warnings


def _table_columns(conn: sqlite3.Connection, table_name: str) -> set[str]:
    rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    return {str(row[1]) for row in rows}


def _candidate_table_exists(conn: sqlite3.Connection) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'candidate_evaluations'"
    ).fetchone()
    return row is not None


def _database_row_score(row: dict[str, Any], metrics: dict[str, Any]) -> float:
    engine_score = max(0.0, min(100.0, safe_float(row.get("score"))))
    score = 42.0 + (engine_score * 0.25)
    if row.get("passed_constraints"):
        score += 12.0
    try:
        rank = int(row.get("rank"))
    except (TypeError, ValueError):
        rank = 0
    if rank > 0:
        score += max(0.0, 12.0 - rank)
    relative_volume = safe_float(metrics.get("relative_volume"))
    if relative_volume:
        score += min(8.0, relative_volume * 2.0)
    return max(35.0, min(92.0, score))


def discover_database_recent_candidates(
    *,
    db_path: str,
    max_tickers: int,
    discovered_at: str,
    row_limit: int | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    warnings: list[str] = []
    if db_path != ":memory:" and not Path(db_path).exists():
        return [], [f"Discovery database source unavailable; SQLite file not found: {db_path}."]

    limit = _bounded_int(row_limit, max(max_tickers * 10, 50), minimum=1, maximum=500)
    conn: sqlite3.Connection | None = None
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        with conn:
            if not _candidate_table_exists(conn):
                return [], ["Discovery database source unavailable; candidate_evaluations table is missing."]
            columns = _table_columns(conn, "candidate_evaluations")
            missing = {"ticker", "created_at"} - columns
            if missing:
                return [], [f"Discovery database source unavailable; candidate_evaluations is missing columns: {', '.join(sorted(missing))}."]
            rows = conn.execute(
                """
                SELECT *
                FROM candidate_evaluations
                ORDER BY datetime(created_at) DESC, id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
    except sqlite3.Error as exc:
        return [], [f"Discovery database source unavailable: {exc}."]
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass

    best_by_ticker: dict[str, dict[str, Any]] = {}
    for raw_row in rows:
        row = dict(raw_row)
        ticker = str(row.get("ticker") or "").strip().upper()
        validated = validate_ticker_universe([ticker], max_tickers=1)
        if not validated.get("ok"):
            warnings.extend(str(item) for item in validated.get("errors", []) if item)
            continue

        metrics = _deserialize_json(row.get("metrics_json"))
        metrics = metrics if isinstance(metrics, dict) else {}
        constraints = _deserialize_json(row.get("constraint_results_json"))
        constraints = constraints if isinstance(constraints, dict) else {}
        failed_constraints = _deserialize_json(row.get("failed_constraints_json"))
        score = _database_row_score(row, metrics)
        candidate = DiscoveryCandidate(
            ticker=validated["tickers"][0],
            source="candidate_evaluations",
            source_type="database_recent",
            discovered_at=discovered_at,
            as_of=str(row.get("created_at") or discovered_at),
            discovery_score=score,
            reasons=unique_texts(
                [
                    "Recent deterministic scanner candidate stored locally.",
                    "Stored candidate previously passed scanner constraints." if row.get("passed_constraints") else "",
                    f"Stored engine score: {row.get('score')}." if row.get("score") is not None else "",
                    f"Stored rank: {row.get('rank')}." if row.get("rank") is not None else "",
                ]
            ),
            raw_metadata={
                "candidate_evaluation_id": row.get("id"),
                "scanner_run_id": row.get("scanner_run_id"),
                "created_at": row.get("created_at"),
                "asset_type": row.get("asset_type"),
                "direction": row.get("direction"),
                "setup_type": row.get("setup_type"),
                "passed_constraints": row.get("passed_constraints"),
                "candidate_score": row.get("score"),
                "rank": row.get("rank"),
                "rejection_reason": row.get("rejection_reason"),
                "failed_constraints": failed_constraints,
                "metrics": {
                    key: metrics.get(key)
                    for key in ("relative_volume", "risk_reward", "current_price", "data_freshness")
                    if key in metrics
                },
                "constraint_status": constraints.get("recommendation_status") or constraints.get("status"),
            },
            point_in_time_safe=True,
            requires_live_validation=True,
        ).to_dict()
        existing = best_by_ticker.get(candidate["ticker"])
        if existing is None or safe_float(candidate.get("discovery_score")) > safe_float(existing.get("discovery_score")):
            best_by_ticker[candidate["ticker"]] = candidate

    ranked = sorted(best_by_ticker.values(), key=lambda row: (-safe_float(row.get("discovery_score")), str(row.get("ticker"))))
    return ranked[:max_tickers], unique_texts(warnings)


def _merge_candidates(candidates: list[dict[str, Any]], max_tickers: int) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for candidate in candidates:
        ticker = str(candidate.get("ticker") or "").strip().upper()
        if not ticker:
            continue
        grouped.setdefault(ticker, []).append(candidate)

    merged: list[dict[str, Any]] = []
    for ticker, rows in grouped.items():
        ranked = sorted(rows, key=lambda row: safe_float(row.get("discovery_score")), reverse=True)
        primary = dict(ranked[0])
        primary["ticker"] = ticker
        primary["discovery_score"] = safe_float(primary.get("discovery_score"))
        primary["sources"] = unique_texts([row.get("source_type") for row in ranked])
        primary["reasons"] = unique_texts([reason for row in ranked for reason in row.get("reasons", [])])
        primary["warnings"] = unique_texts([warning for row in ranked for warning in row.get("warnings", [])])
        primary["secondary_sources"] = [
            {
                "source": row.get("source"),
                "source_type": row.get("source_type"),
                "discovery_score": row.get("discovery_score"),
                "reasons": row.get("reasons", []),
                "raw_metadata": row.get("raw_metadata", {}),
            }
            for row in ranked[1:]
        ]
        raw_metadata = dict(primary.get("raw_metadata") or {})
        raw_metadata["all_discovery_sources"] = [
            {
                "source": row.get("source"),
                "source_type": row.get("source_type"),
                "discovery_score": row.get("discovery_score"),
                "as_of": row.get("as_of"),
            }
            for row in ranked
        ]
        primary["raw_metadata"] = raw_metadata
        primary["point_in_time_safe"] = all(bool(row.get("point_in_time_safe", True)) for row in ranked)
        primary["requires_live_validation"] = True
        merged.append(primary)

    return sorted(merged, key=lambda row: (-safe_float(row.get("discovery_score")), str(row.get("ticker"))))[:max_tickers]


def discover_candidates(
    *,
    db_path: str = "strategy_library.db",
    requested_sources: list[str] | None = None,
    max_tickers: int = 20,
    fallback_universes: list[str] | None = None,
    discovered_at: str | None = None,
) -> dict[str, Any]:
    timestamp = discovered_at or utc_now_iso()
    sources = requested_sources or DEFAULT_DISCOVERY_SOURCES
    max_count = _bounded_int(max_tickers, 20, minimum=1, maximum=MAX_DISCOVERED_TICKERS)
    warnings: list[str] = []
    errors: list[str] = []
    candidates: list[dict[str, Any]] = []

    for source in sources:
        normalized = str(source or "").strip().lower()
        if normalized == "manual_hotlist":
            rows, source_warnings = discover_manual_hotlist_candidates(max_tickers=max_count, discovered_at=timestamp)
        elif normalized == "database_recent":
            rows, source_warnings = discover_database_recent_candidates(db_path=db_path, max_tickers=max_count, discovered_at=timestamp)
        elif normalized == "liquid_fallback":
            rows, source_warnings = discover_liquid_fallback_candidates(
                max_tickers=max_count,
                discovered_at=timestamp,
                universes=fallback_universes or DEFAULT_FALLBACK_UNIVERSES,
            )
        else:
            rows, source_warnings = [], [f"Unknown discovery source ignored: {source}."]
        candidates.extend(rows)
        warnings.extend(source_warnings)

    merged = _merge_candidates(candidates, max_count)
    tickers = [candidate["ticker"] for candidate in merged]
    return {
        "ok": True,
        "discovery_version": DISCOVERY_VERSION,
        "discovered_at": timestamp,
        "as_of": max([candidate.get("as_of") or timestamp for candidate in merged], default=timestamp),
        "requested_sources": sources,
        "sources_used": unique_texts([source for candidate in merged for source in candidate.get("sources", [candidate.get("source_type")])]),
        "candidates": merged,
        "tickers": tickers,
        "discovered_count": len(tickers),
        "warnings": unique_texts(warnings),
        "errors": unique_texts(errors),
        "point_in_time_safe": all(bool(candidate.get("point_in_time_safe", True)) for candidate in merged),
        "requires_live_validation": True,
        "discovery_used": False,
        "fallback_used": False,
        "bypass_reason": None,
        "max_discovered_tickers": max_count,
    }


__all__ = [
    "DEFAULT_DISCOVERY_SOURCES",
    "discover_candidates",
    "discover_database_recent_candidates",
    "discover_liquid_fallback_candidates",
    "discover_manual_hotlist_candidates",
    "empty_discovery_result",
]
