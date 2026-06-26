from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable
import json
import sqlite3

from db.schema_manager import apply_pending_migrations
from market.calendar import is_market_day


GRADING_VERSION = "candidate_outcome_v1"
DEFAULT_HORIZONS = [1, 3, 5, 10, 20]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _as_date(value: Any) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return datetime.fromisoformat(str(value).replace("Z", "+00:00")[:10]).date()


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


def _safe_float(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _row_to_snapshot(row: sqlite3.Row) -> dict:
    payload = dict(row)
    for key in (
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


def add_trading_sessions(start: date, sessions: int) -> date:
    current = start
    remaining = max(0, int(sessions))
    while remaining:
        current += timedelta(days=1)
        if is_market_day(current):
            remaining -= 1
    return current


def _normalize_bars(payload: Any) -> tuple[list[dict], bool, list[str]]:
    warnings: list[str] = []
    option_history = False
    if callable(payload):
        payload = payload()
    if isinstance(payload, dict):
        option_history = bool(payload.get("option_price_history_available") or payload.get("exact_option_history_available"))
        if payload.get("ok") is False:
            return [], option_history, [str(payload.get("error") or "Price loader returned unavailable data.")]
        bars = payload.get("bars") or payload.get("data") or []
    else:
        bars = payload
    normalized: list[dict] = []
    for row in bars if isinstance(bars, list) else []:
        if not isinstance(row, dict):
            continue
        close = _safe_float(row.get("close") if row.get("close") is not None else row.get("ending_price"))
        high = _safe_float(row.get("high"))
        low = _safe_float(row.get("low"))
        timestamp = row.get("timestamp") or row.get("date") or row.get("time")
        if close is None or timestamp is None:
            continue
        normalized.append(
            {
                "timestamp": str(timestamp),
                "date": _as_date(timestamp).isoformat(),
                "open": _safe_float(row.get("open")),
                "high": high if high is not None else close,
                "low": low if low is not None else close,
                "close": close,
            }
        )
    normalized.sort(key=lambda item: item["date"])
    if not normalized:
        warnings.append("No usable future price bars were available.")
    return normalized, option_history, warnings


def _default_price_loader(snapshot: dict, horizon_sessions: int) -> dict:
    return {"ok": False, "bars": [], "error": "No price_loader was provided; outcome remains unavailable."}


def _starting_price(snapshot: dict, underlying_only: bool) -> float | None:
    if snapshot.get("asset_type") == "option" and not underlying_only:
        return _safe_float(snapshot.get("mid") or snapshot.get("ask") or snapshot.get("bid"))
    return _safe_float(snapshot.get("entry_price") or snapshot.get("underlying_price"))


def _direction(snapshot: dict) -> str:
    direction = str(snapshot.get("direction") or "long").lower()
    return "short" if direction == "short" else "long"


def _return_for_direction(start: float, end: float, direction: str) -> float:
    if start == 0:
        return 0.0
    raw = (end - start) / start
    return -raw if direction == "short" else raw


def _mfe_mae(snapshot: dict, bars: list[dict], start: float, direction: str) -> tuple[float | None, float | None]:
    if not bars or start == 0:
        return None, None
    if direction == "short":
        favorable = max((start - float(row["low"])) / start for row in bars)
        adverse = min((start - float(row["high"])) / start for row in bars)
    else:
        favorable = max((float(row["high"]) - start) / start for row in bars)
        adverse = min((float(row["low"]) - start) / start for row in bars)
    return favorable, adverse


def _target_stop_hits(snapshot: dict, bars: list[dict], direction: str) -> tuple[bool, bool, str | None, str | None, bool]:
    target = _safe_float(snapshot.get("target_price"))
    stop = _safe_float(snapshot.get("stop_loss"))
    target_hit = False
    stop_hit = False
    first_result = None
    first_timestamp = None
    ambiguous = False
    if target is None or stop is None:
        return False, False, None, None, False
    for row in bars:
        high = float(row["high"])
        low = float(row["low"])
        if direction == "short":
            target_touched = low <= target
            stop_touched = high >= stop
        else:
            target_touched = high >= target
            stop_touched = low <= stop
        target_hit = target_hit or target_touched
        stop_hit = stop_hit or stop_touched
        if first_result is None:
            if target_touched and stop_touched:
                ambiguous = True
                first_result = "ambiguous"
                first_timestamp = row["timestamp"]
                break
            if target_touched:
                first_result = "target"
                first_timestamp = row["timestamp"]
                break
            if stop_touched:
                first_result = "stop"
                first_timestamp = row["timestamp"]
                break
    return target_hit, stop_hit, first_result, first_timestamp, ambiguous


def _r_multiple(snapshot: dict, end_price: float, start_price: float, direction: str) -> float | None:
    stop = _safe_float(snapshot.get("stop_loss"))
    if stop is None:
        return None
    risk = abs(start_price - stop)
    if risk == 0:
        return None
    pnl = (start_price - end_price) if direction == "short" else (end_price - start_price)
    return pnl / risk


def grade_snapshot_horizon(snapshot: dict, horizon_sessions: int, price_loader: Callable | None, as_of_date: date) -> dict:
    snapshot_date = _as_date(snapshot.get("snapshot_at"))
    maturity = add_trading_sessions(snapshot_date, horizon_sessions)
    if maturity > as_of_date:
        return {
            "outcome_status": "pending",
            "horizon_maturity_date": maturity.isoformat(),
            "warnings": ["Outcome horizon has not matured yet."],
            "errors": [],
        }

    loader = price_loader or _default_price_loader
    try:
        price_payload = loader(snapshot, horizon_sessions)
    except Exception as exc:
        price_payload = {"ok": False, "bars": [], "error": str(exc)}
    bars, option_history, warnings = _normalize_bars(price_payload)
    errors: list[str] = []
    if not bars:
        errors.extend(warnings)
        return {
            "outcome_status": "unavailable",
            "horizon_maturity_date": maturity.isoformat(),
            "warnings": [],
            "errors": errors,
        }

    asset_type = str(snapshot.get("asset_type") or "stock").lower()
    underlying_only = asset_type == "option" and not option_history
    if asset_type == "option" and underlying_only:
        warnings.append("Option price history unavailable; grading underlying thesis only, not exact option P/L.")
    start = _starting_price(snapshot, underlying_only=underlying_only)
    if start is None:
        return {
            "outcome_status": "unavailable",
            "horizon_maturity_date": maturity.isoformat(),
            "warnings": warnings,
            "errors": ["Starting price is unavailable."],
        }
    end = float(bars[-1]["close"])
    direction = _direction(snapshot)
    forward_return = _return_for_direction(start, end, direction)
    mfe, mae = _mfe_mae(snapshot, bars, start, direction)
    target_hit, stop_hit, first_result, first_timestamp, ambiguous = _target_stop_hits(snapshot, bars, direction)
    return {
        "outcome_status": "graded",
        "horizon_maturity_date": maturity.isoformat(),
        "starting_price": start,
        "ending_price": end,
        "forward_return": forward_return,
        "maximum_favorable_excursion": mfe,
        "maximum_adverse_excursion": mae,
        "target_hit": target_hit,
        "stop_hit": stop_hit,
        "first_hit_result": first_result,
        "first_hit_timestamp": first_timestamp,
        "r_multiple": _r_multiple(snapshot, end, start, direction),
        "underlying_only": underlying_only,
        "option_price_history_available": bool(option_history) if asset_type == "option" else False,
        "ambiguous": ambiguous,
        "warnings": warnings,
        "errors": errors,
    }


def _upsert_outcome(conn: sqlite3.Connection, snapshot_id: int, horizon: int, graded: dict) -> tuple[str, bool]:
    existing = conn.execute(
        "SELECT id FROM candidate_forward_outcomes WHERE candidate_snapshot_id = ? AND horizon_sessions = ?",
        (snapshot_id, horizon),
    ).fetchone()
    values = (
        snapshot_id,
        horizon,
        graded.get("horizon_maturity_date"),
        _now_iso(),
        graded.get("outcome_status"),
        _safe_float(graded.get("starting_price")),
        _safe_float(graded.get("ending_price")),
        _safe_float(graded.get("forward_return")),
        _safe_float(graded.get("maximum_favorable_excursion")),
        _safe_float(graded.get("maximum_adverse_excursion")),
        1 if graded.get("target_hit") else 0,
        1 if graded.get("stop_hit") else 0,
        graded.get("first_hit_result"),
        graded.get("first_hit_timestamp"),
        _safe_float(graded.get("r_multiple")),
        1 if graded.get("underlying_only") else 0,
        1 if graded.get("option_price_history_available") else 0,
        1 if graded.get("ambiguous") else 0,
        _json(graded.get("warnings", [])),
        _json(graded.get("errors", [])),
    )
    if existing:
        conn.execute(
            """
            UPDATE candidate_forward_outcomes SET
                horizon_maturity_date = ?, graded_at = ?, outcome_status = ?,
                starting_price = ?, ending_price = ?, forward_return = ?,
                maximum_favorable_excursion = ?, maximum_adverse_excursion = ?,
                target_hit = ?, stop_hit = ?, first_hit_result = ?, first_hit_timestamp = ?,
                r_multiple = ?, underlying_only = ?, option_price_history_available = ?,
                ambiguous = ?, warnings_json = ?, errors_json = ?
            WHERE candidate_snapshot_id = ? AND horizon_sessions = ?
            """,
            values[2:] + (snapshot_id, horizon),
        )
        return "updated", graded.get("outcome_status") == "graded"
    conn.execute(
        """
        INSERT INTO candidate_forward_outcomes (
            candidate_snapshot_id, horizon_sessions, horizon_maturity_date, graded_at,
            outcome_status, starting_price, ending_price, forward_return,
            maximum_favorable_excursion, maximum_adverse_excursion, target_hit, stop_hit,
            first_hit_result, first_hit_timestamp, r_multiple, underlying_only,
            option_price_history_available, ambiguous, warnings_json, errors_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        values,
    )
    return "created", graded.get("outcome_status") == "graded"


def grade_mature_candidate_outcomes(
    db_path: str = "strategy_library.db",
    as_of: str | None = None,
    horizons: list[int] | None = None,
    price_loader: Callable | None = None,
) -> dict:
    selected_horizons = horizons or DEFAULT_HORIZONS
    response = {
        "ok": True,
        "grading_version": GRADING_VERSION,
        "as_of": as_of,
        "horizons": selected_horizons,
        "snapshots_considered": 0,
        "outcomes_created": 0,
        "outcomes_updated": 0,
        "pending_count": 0,
        "unavailable_count": 0,
        "ambiguous_count": 0,
        "stock_outcome_count": 0,
        "exact_option_outcome_count": 0,
        "underlying_only_option_count": 0,
        "warnings": [],
        "errors": [],
    }
    try:
        apply_pending_migrations(db_path)
        as_of_date = _as_date(as_of) if as_of else datetime.now(timezone.utc).date()
        with _connect(db_path) as conn:
            rows = conn.execute("SELECT * FROM candidate_snapshots ORDER BY id ASC").fetchall()
            response["snapshots_considered"] = len(rows)
            for row in rows:
                snapshot = _row_to_snapshot(row)
                for horizon in selected_horizons:
                    graded = grade_snapshot_horizon(snapshot, int(horizon), price_loader, as_of_date)
                    status, graded_ok = _upsert_outcome(conn, int(snapshot["id"]), int(horizon), graded)
                    if status == "created":
                        response["outcomes_created"] += 1
                    else:
                        response["outcomes_updated"] += 1
                    if graded["outcome_status"] == "pending":
                        response["pending_count"] += 1
                    elif graded["outcome_status"] == "unavailable":
                        response["unavailable_count"] += 1
                    if graded.get("ambiguous"):
                        response["ambiguous_count"] += 1
                    if graded_ok:
                        if snapshot.get("asset_type") == "option":
                            if graded.get("underlying_only"):
                                response["underlying_only_option_count"] += 1
                            else:
                                response["exact_option_outcome_count"] += 1
                        else:
                            response["stock_outcome_count"] += 1
                    response["warnings"].extend(graded.get("warnings", []))
        response["warnings"] = list(dict.fromkeys(str(item) for item in response["warnings"] if item))
        return response
    except Exception as exc:
        response["ok"] = False
        response["errors"].append(str(exc))
        return response
