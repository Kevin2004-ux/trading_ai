from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import math
import sqlite3
import uuid
from typing import Any, Callable


DEFAULT_DB_PATH = "strategy_library.db"
MIN_OVERLAP_DAYS = 20


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(numeric):
        return None
    return numeric


def _parse_timestamp(value: Any) -> str | None:
    if value is None:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        return str(value)[:10] if str(value) else None


def _extract_bars(payload: Any) -> list[dict]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        return []
    if isinstance(payload.get("bars"), list):
        return [item for item in payload["bars"] if isinstance(item, dict)]
    data = payload.get("data")
    if isinstance(data, dict) and isinstance(data.get("bars"), list):
        return [item for item in data["bars"] if isinstance(item, dict)]
    if isinstance(payload.get("results"), list):
        return [item for item in payload["results"] if isinstance(item, dict)]
    return []


def _close_by_date(raw_bars: Any, lookback_days: int) -> tuple[dict[str, float], list[str]]:
    warnings: list[str] = []
    bars = _extract_bars(raw_bars)
    if not bars:
        return {}, ["No historical bars available."]

    closes: dict[str, float] = {}
    for bar in bars[-max(int(lookback_days) + 5, 2):]:
        date_key = _parse_timestamp(bar.get("timestamp") or bar.get("date") or bar.get("time") or bar.get("t"))
        close = _safe_float(bar.get("close") if "close" in bar else bar.get("c"))
        if date_key and close is not None and close > 0:
            closes[date_key] = close

    if len(closes) < 2:
        warnings.append("Insufficient valid close history.")
    return dict(sorted(closes.items())), warnings


def _returns(closes: dict[str, float]) -> dict[str, float]:
    dates = sorted(closes)
    output: dict[str, float] = {}
    for previous_date, current_date in zip(dates, dates[1:]):
        previous = closes.get(previous_date)
        current = closes.get(current_date)
        if previous in (None, 0) or current is None:
            continue
        output[current_date] = (current - previous) / previous
    return output


def _correlation(left: list[float], right: list[float]) -> float | None:
    if len(left) < 2 or len(right) < 2 or len(left) != len(right):
        return None
    left_mean = sum(left) / len(left)
    right_mean = sum(right) / len(right)
    left_deltas = [value - left_mean for value in left]
    right_deltas = [value - right_mean for value in right]
    left_var = sum(value * value for value in left_deltas)
    right_var = sum(value * value for value in right_deltas)
    if left_var <= 0 or right_var <= 0:
        return None
    covariance = sum(a * b for a, b in zip(left_deltas, right_deltas))
    return max(-1.0, min(1.0, covariance / math.sqrt(left_var * right_var)))


def build_correlation_matrix(
    price_history: dict[str, list[dict]],
    lookback_days: int = 60,
) -> dict:
    warnings: list[str] = []
    errors: list[str] = []
    if not isinstance(price_history, dict) or not price_history:
        return {
            "ok": False,
            "lookback_days": lookback_days,
            "tickers": [],
            "correlations": {},
            "warnings": [],
            "errors": ["price_history must be a non-empty dictionary."],
        }

    returns_by_ticker: dict[str, dict[str, float]] = {}
    for raw_ticker, raw_bars in price_history.items():
        ticker = str(raw_ticker or "").strip().upper()
        if not ticker:
            continue
        closes, close_warnings = _close_by_date(raw_bars, lookback_days)
        warnings.extend(f"{ticker}: {warning}" for warning in close_warnings)
        ticker_returns = _returns(closes)
        if len(ticker_returns) < 2:
            warnings.append(f"{ticker}: insufficient return history.")
            continue
        if len(set(round(value, 12) for value in ticker_returns.values())) <= 1:
            warnings.append(f"{ticker}: constant returns; correlations unavailable.")
            continue
        returns_by_ticker[ticker] = ticker_returns

    tickers = sorted(returns_by_ticker)
    correlations: dict[str, dict[str, float]] = {ticker: {} for ticker in tickers}
    for left_index, left_ticker in enumerate(tickers):
        correlations[left_ticker][left_ticker] = 1.0
        for right_ticker in tickers[left_index + 1:]:
            overlap_dates = sorted(set(returns_by_ticker[left_ticker]) & set(returns_by_ticker[right_ticker]))
            if len(overlap_dates) < MIN_OVERLAP_DAYS:
                warnings.append(f"{left_ticker}/{right_ticker}: insufficient overlapping return history.")
                continue
            left_values = [returns_by_ticker[left_ticker][date_key] for date_key in overlap_dates]
            right_values = [returns_by_ticker[right_ticker][date_key] for date_key in overlap_dates]
            corr = _correlation(left_values, right_values)
            if corr is None:
                warnings.append(f"{left_ticker}/{right_ticker}: correlation unavailable due to constant or malformed returns.")
                continue
            correlations[left_ticker][right_ticker] = round(corr, 4)
            correlations[right_ticker][left_ticker] = round(corr, 4)

    if not tickers:
        errors.append("No tickers had enough usable return history.")

    return {
        "ok": not errors,
        "lookback_days": lookback_days,
        "tickers": tickers,
        "correlations": correlations,
        "warnings": warnings,
        "errors": errors,
    }


def _connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def _ensure_table(db_path: str) -> None:
    from db.schema_manager import apply_pending_migrations

    apply_pending_migrations(db_path)


def _row_to_snapshot(row: sqlite3.Row | None, max_age_hours: int | None = None) -> dict | None:
    if row is None:
        return None
    snapshot = dict(row)
    for key in ("tickers_json", "matrix_json", "summary_json"):
        try:
            snapshot[key] = json.loads(snapshot[key]) if snapshot.get(key) else None
        except json.JSONDecodeError:
            pass
    created_at = datetime.fromisoformat(str(snapshot["created_at"]).replace("Z", "+00:00"))
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    age_hours = (datetime.now(timezone.utc) - created_at).total_seconds() / 3600.0
    snapshot["age_hours"] = round(age_hours, 3)
    snapshot["is_stale"] = bool(max_age_hours is not None and age_hours > max_age_hours)
    return snapshot


def save_correlation_snapshot(db_path: str, matrix_result: dict) -> dict:
    try:
        if not isinstance(matrix_result, dict):
            return {"ok": False, "error": "matrix_result must be a dictionary."}
        _ensure_table(db_path)
        snapshot_id = str(matrix_result.get("snapshot_id") or uuid.uuid4())
        created_at = _now_iso()
        summary = {
            "ticker_count": len(matrix_result.get("tickers", []) or []),
            "warning_count": len(matrix_result.get("warnings", []) or []),
            "error_count": len(matrix_result.get("errors", []) or []),
            "ok": bool(matrix_result.get("ok")),
        }
        with _connect(db_path) as conn:
            conn.execute(
                """
                INSERT INTO correlation_snapshots (
                    snapshot_id, created_at, lookback_days, tickers_json,
                    matrix_json, summary_json, source
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    snapshot_id,
                    created_at,
                    int(matrix_result.get("lookback_days") or 60),
                    json.dumps(matrix_result.get("tickers", [])),
                    json.dumps(matrix_result.get("correlations", {})),
                    json.dumps(matrix_result.get("summary") or summary),
                    matrix_result.get("source") or "system",
                ),
            )
        return {
            "ok": True,
            "snapshot_id": snapshot_id,
            "created_at": created_at,
            "summary": summary,
            "error": None,
        }
    except (sqlite3.Error, TypeError, ValueError) as exc:
        return {"ok": False, "error": str(exc)}


def get_latest_correlation_snapshot(db_path: str, max_age_hours: int = 36) -> dict:
    try:
        _ensure_table(db_path)
        with _connect(db_path) as conn:
            row = conn.execute(
                "SELECT * FROM correlation_snapshots ORDER BY created_at DESC, id DESC LIMIT 1"
            ).fetchone()
        snapshot = _row_to_snapshot(row, max_age_hours=max_age_hours)
        if snapshot is None:
            return {
                "ok": False,
                "snapshot": None,
                "is_stale": True,
                "error": "No correlation snapshot found.",
            }
        return {
            "ok": not snapshot["is_stale"],
            "snapshot": snapshot,
            "is_stale": snapshot["is_stale"],
            "error": "Latest correlation snapshot is stale." if snapshot["is_stale"] else None,
        }
    except sqlite3.Error as exc:
        return {"ok": False, "snapshot": None, "is_stale": True, "error": str(exc)}


def refresh_correlation_snapshot(
    db_path: str,
    tickers: list[str],
    price_history_provider: Callable[[str, int], Any],
    lookback_days: int = 60,
) -> dict:
    warnings: list[str] = []
    price_history: dict[str, list[dict]] = {}
    for raw_ticker in tickers or []:
        ticker = str(raw_ticker or "").strip().upper()
        if not ticker:
            continue
        try:
            payload = price_history_provider(ticker, lookback_days)
        except Exception as exc:
            warnings.append(f"{ticker}: price history provider failed: {exc}")
            continue
        bars = _extract_bars(payload)
        if not bars:
            warnings.append(f"{ticker}: no bars returned by price history provider.")
            continue
        price_history[ticker] = bars

    matrix_result = build_correlation_matrix(price_history, lookback_days=lookback_days)
    matrix_result["source"] = "refresh"
    matrix_result["warnings"] = list(matrix_result.get("warnings", [])) + warnings
    save_result = save_correlation_snapshot(db_path, matrix_result) if matrix_result.get("tickers") else {"ok": False, "error": "No usable tickers to save."}
    return {
        "ok": bool(matrix_result.get("ok")) and bool(save_result.get("ok")),
        "matrix": matrix_result,
        "save_result": save_result,
        "warnings": matrix_result.get("warnings", []),
        "errors": list(matrix_result.get("errors", [])) + ([] if save_result.get("ok") else [save_result.get("error", "Failed to save correlation snapshot.")]),
    }
